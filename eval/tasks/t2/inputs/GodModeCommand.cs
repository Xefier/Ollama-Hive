using System.Collections.Generic;
using UnityEngine;
using Xefier.Core;

namespace ConsoleUtility
{
    [AutoRegisterConsoleCommand]
    public class GodModeCommand : ConsoleCommandBase, IConsoleCommand
    {
        // Kept for the session: the next scene's player reads it back (Player_AffectorsController.ApplySessionGodMode)
        private const string VariableName = Player_AffectorsController.GodModeVariable;

        public string name => "god";

        public string summary => "Sets God Mode (No Death)";

        public string help => @"Command: god true (Turns God Mode On), god false (Turns God Mode Off). Stays on through scene loads until god false.";

        public IEnumerable<Console.Alias> aliases { get { yield break; } }

        protected override void ExecuteImpl(string[] args)
        {
            if (args.Length == 0)
            {
                LogHelp(this);
                return;
            }

            bool godMode;
            switch (args[0])
            {
                case "true":
                    godMode = true;
                    break;
                case "false":
                    godMode = false;
                    break;
                default:
                    DebugX.LogWarning("incorrect argument for god: " + args[0]);
                    return;
            }

            // Stored even with no player yet (main menu, loading), so the next player spawned picks it up
            GlobalVars.Instance.Set(VariableName, godMode);
            Player_AffectorsController.LocalPlayerInstance?.SetGodMode(godMode);
        }
    }
}
