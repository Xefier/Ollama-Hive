using System.Collections.Generic;
using System.Security.Cryptography;
using System.Text;
using System;

namespace ConsoleUtility
{
    [AutoRegisterConsoleCommand]
    public abstract class ConsoleCommandBase
    {
        private const string CORRECT_PASSWORD_HASH = "1f5c56f369700c5d4fdcd966895513e0115281d082e4a10889d428bf21a73ce0";
        public const string Save = "Settings";
        public const string PasswordKey = "Password";

        /// <summary>
        /// The Hunt's password, separate from the console password (owner, task 86e3x5puh): the hunt command takes this
        /// one alone, typed with <c>hunt password</c> into its own key of the "Settings" save, so it never overwrites
        /// the console password.
        /// </summary>
        protected const string HUNT_PASSWORD_HASH = "fe1cb261b8c122d51ac4c28cb5f817bc9527a629dbc167d3f39a296955623864";
        public const string HuntPasswordKey = "HuntPassword";
        private const string Space = "+";

        /// <summary>
        /// Optional veto on password-gated commands: returns why they are blocked right now, or null when they are not.
        /// Commands that don't need the password (IsEnabled overrides that return true, or "base || x" for x) are
        /// unaffected. Not consulted in the editor, where every command is enabled.
        /// </summary>
        public static Func<string> PasswordBlockReason;

        /// <summary>
        /// Development builds only: true while a tool runs commands it was handed when the game was launched (mobile's
        /// LaunchConsoleCommand, which times entity spawns on a phone, where the console cannot be typed into). Those
        /// commands skip the password and its veto, as in the editor. Release builds never read it.
        /// </summary>
        public static bool RunningLaunchCommands;

        protected virtual bool IsEnabled(string[] args) => IsPasswordAccepted(PasswordKey, CORRECT_PASSWORD_HASH);

        /// <summary>
        /// Whether a password-gated command may run: always in the editor and for a development build's launch
        /// commands; otherwise only outside the <see cref="PasswordBlockReason"/> veto and with the password saved
        /// under <paramref name="key"/> in the "Settings" save hashing to <paramref name="passwordHash"/>. The console
        /// password is (<see cref="PasswordKey"/>, its hash); a command with a password of its own passes its own pair.
        /// </summary>
        protected static bool IsPasswordAccepted(string key, string passwordHash)
        {
#if UNITY_EDITOR
            return true;
#else
#if DEVELOPMENT_BUILD
            if (RunningLaunchCommands)
                return true;
#endif
            return GetPasswordBlockReason() == null && IsSavedPasswordCorrect(key, passwordHash);
#endif
        }

        /// <summary>
        /// Whether the password saved under <paramref name="key"/> hashes to <paramref name="passwordHash"/>: the check
        /// a build makes, without the editor's pass, so a test can see a refusal in the editor too.
        /// </summary>
        public static bool IsSavedPasswordCorrect(string key, string passwordHash)
        {
            var save = Xefier.Persistence.Saves.Get(Save);
            return save != null && PasswordMatches(save.Get<string>(key), passwordHash);
        }

        /// <summary>Whether <paramref name="password"/> hashes to <paramref name="passwordHash"/>.</summary>
        private static bool PasswordMatches(string password, string passwordHash)
        {
            return !string.IsNullOrEmpty(password) && HashPassword(password) == passwordHash;
        }

        /// <summary>
        /// Saves a typed password under <paramref name="key"/> in the "Settings" save and writes the save to disk:
        /// the <c>password</c> command's console password, <c>hunt password</c>'s Hunt password.
        /// </summary>
        public static void StorePassword(string key, string password)
        {
            var save = Xefier.Persistence.Saves.Get(Save);
            if (save == null)
            {
                return;
            }

            save.Set(key, password);
            Xefier.Persistence.Saves.Save(Save);
        }

        private static string GetPasswordBlockReason() => PasswordBlockReason?.Invoke();

        public void Execute(string[] args)
        {
            // Console splits the raw line on ' ' before we ever see it, so re-tokenize (honouring quotes) and
            // decode '+' first - IsEnabled inspects args too, so it must see the same values ExecuteImpl does.
            args = Decode(Tokenize(args));

            if (IsEnabled(args))
            {
                ExecuteImpl(args);
            }
            else
            {
                Console.Log("", GetPasswordBlockReason() ?? "Console commands disabled", UnityEngine.LogType.Error);
            }
        }

        /// <summary>
        /// Re-joins the space-split words and re-splits them respecting double quotes, so a name with spaces can be
        /// typed as "Fuse Test" instead of Fuse+Test. Empty words (from double spaces) are dropped.
        /// </summary>
        public static string[] Tokenize(string[] args)
        {
            if (args == null || args.Length == 0) return Array.Empty<string>();

            string line = string.Join(" ", args);
            var tokens = new List<string>();
            var current = new StringBuilder();
            bool inQuotes = false;
            bool started = false;

            for (int i = 0; i < line.Length; i++)
            {
                char c = line[i];

                if (c == '"')
                {
                    inQuotes = !inQuotes;
                    started = true;   // "" is a deliberate empty argument, so keep it
                    continue;
                }

                if (c == ' ' && !inQuotes)
                {
                    if (started)
                    {
                        tokens.Add(current.ToString());
                        current.Length = 0;
                        started = false;
                    }
                    continue;
                }

                current.Append(c);
                started = true;
            }

            if (started) tokens.Add(current.ToString());

            return tokens.ToArray();
        }

        public string[] Decode(string[] args)
        {
            for (int i = 0; i < args.Length; i++)
            {
                args[i] = Decode(args[i]);
            }

            return args;
        }

        public string Decode(string arg)
        {
            //TODO: Find a proper C# utility to decode
            return arg.Contains(Space) ? arg.Replace(Space, " ") : arg;
        }

        /// <summary>
        /// Joins args[start..] back into one name, so an unquoted name with spaces still arrives intact.
        /// Only safe when nothing but the name follows - peel trailing options off the count first.
        /// </summary>
        protected internal static string JoinArgs(string[] args, int start)
        {
            return JoinArgs(args, start, args.Length - start);
        }

        /// <summary>Joins <paramref name="count"/> args starting at <paramref name="start"/> into one name.</summary>
        protected internal static string JoinArgs(string[] args, int start, int count)
        {
            if (args == null || start < 0 || start >= args.Length || count <= 0) return string.Empty;

            if (start + count > args.Length) count = args.Length - start;

            return string.Join(" ", args, start, count);
        }

        /// <summary>
        /// For a name with spaces that has more arguments after it ("rename Grace Chen Grace"), where
        /// <see cref="JoinArgs(string[], int)"/> can't tell where the name ends: finds the longest run of words from
        /// <paramref name="start"/> that <paramref name="isName"/> accepts. <paramref name="end"/> is the index after
        /// the name, where the remaining arguments begin. A quoted name is one argument, so it matches as well.
        /// </summary>
        protected static bool TryMatchName(string[] args, int start, Func<string, bool> isName, out string name, out int end)
        {
            if (args != null && isName != null)
            {
                for (end = args.Length; end > start; end--)
                {
                    name = JoinArgs(args, start, end - start);
                    if (isName(name)) return true;
                }
            }

            name = null;
            end = start;
            return false;
        }

        /// <summary>Case-insensitive match of an argument against a set of literal keywords.</summary>
        protected static bool IsKeyword(string arg, params string[] keywords)
        {
            if (string.IsNullOrEmpty(arg)) return false;

            for (int i = 0; i < keywords.Length; i++)
            {
                if (string.Equals(arg, keywords[i], StringComparison.OrdinalIgnoreCase)) return true;
            }

            return false;
        }

        protected void LogHelp(IConsoleCommand command)
        {
            Console.Log(command.help);
        }

        private static string HashPassword(string password)
        {
            if (string.IsNullOrEmpty(password)) return password;

            using (var sha = SHA256.Create())
            {
                byte[] bytes = sha.ComputeHash(Encoding.UTF8.GetBytes(password));
                var hash = BitConverter.ToString(bytes).Replace("-", "").ToLower();
                return hash;
            }
        }

        protected abstract void ExecuteImpl(string[] args);
    }
}
