// FILE: TileFindCommand.cs
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using DunGen;
using UnityEngine;

namespace ConsoleUtility
{
    /// <summary>
    /// Finds tiles in the current generated level by name. "tilefind <name>" lists matches with position and cull
    /// status, or just a total with "-count".
    /// </summary>
    [AutoRegisterConsoleCommand]
    public class TileFindCommand : ConsoleCommandBase, IConsoleCommand
    {
        // Past this many matching lines the per-line detail stops; the totals still cover them all.
        private const int MaxMatchLines = 25;

        public string name => "tilefind";
        public string summary => "Tile: find spawned tiles by name";

        // "\n" rather than a verbatim string, so a CRLF checkout doesn't carry '\r's into the console.
        public string help =>
            "Command: tilefind <text> [-count]\n" +
            "* <text>       : lists all tiles whose GameObject name contains <text>, case-insensitive (tilefind Big Tile\n" +
            "                finds \"BigTile_03\"), showing name, world position rounded to metres, and cull status.\n" +
            "                At most 25 lines are shown per run; the final line gives the full total.\n" +
            "* -count       : shows only the final total line, not the per-tile list.";

        public IEnumerable<Console.Alias> aliases { get { yield break; } }

        protected override bool IsEnabled(string[] args) => true;

        protected override void ExecuteImpl(string[] args)
        {
            if (args.Length == 0)
            {
                LogHelp(this);
                return;
            }

            // Peel the trailing option first, so a name with spaces is handled correctly by TryMatchName.
            bool countOnly = false;
            if (IsKeyword(args[args.Length - 1], "-count"))
            {
                args[args.Length - 1] = null; // Remove it from consideration as part of the name
                countOnly = true;
            }

            // Join remaining args into the search term (handles spaces)
            string searchTerm = JoinArgs(args, 0, args.Length - (countOnly ? 1 : 0));

            if (string.IsNullOrEmpty(searchTerm))
            {
                LogHelp(this);
                return;
            }

            Find(searchTerm, countOnly);
        }

        private void Find(string term, bool countOnly)
        {
            var generator = DungeonGenerator.Instance;
            if (generator == null || generator.CurrentDungeon == null)
            {
                Console.Log(name, "No generated level", LogType.Warning);
                return;
            }

            var allTiles = generator.CurrentDungeon.AllTiles;
            int totalMatches = 0;
            int culledCount = 0;
            int visibleCount = 0;

            // We iterate once to count, then again (or store) for the list. To avoid storing thousands of objects if not needed:
            // If we need the list, we buffer it. If countOnly is true, we just count.
            var matchesBuffer = new List<string>();

            foreach (var tile in allTiles)
            {
                if (tile == null) continue;

                // Check if name contains the term (case-insensitive)
                if (!tile.name.Contains(term, StringComparison.OrdinalIgnoreCase))
                    continue;

                totalMatches++;
                bool isCulled = tile.IsCulled;
                if (isCulled) culledCount++;
                else visibleCount++;

                if (!countOnly)
                {
                    // Format: "Name [X, Y, Z] (culled/visible)"
                    var pos = tile.transform.position;
                    string detail = $"{tile.name} [{Mathf.RoundToInt(pos.x)}, {Mathf.RoundToInt(pos.y)}, {Mathf.RoundToInt(pos.z)}] ({(isCulled ? "culled" : "visible")})";
                    matchesBuffer.Add(detail);
                }
            }

            var report = new StringBuilder();

            if (!countOnly)
            {
                for (int i = 0; i < matchesBuffer.Count && i < MaxMatchLines; i++)
                {
                    report.Append(matchesBuffer[i]).Append('\n');
                }

                if (matchesBuffer.Count > MaxMatchLines)
                {
                    report.Append($"... and {matchesBuffer.Count - MaxMatchLines} more\n");
                }
            }

            report.Append($"{totalMatches} of {allTiles.Count} tiles match '{term}' ({culledCount} culled)");

            Console.Log(name, report.ToString());
        }
    }
}

- Assumed `IConsoleCommand` is in the global namespace or imported via the project's standard Unity setup (seen in provided files).
- Used `Mathf.RoundToInt` for rounding to whole metres as it matches Unity style.
- The logic assumes `DungeonGenerator.Instance` returns a static singleton consistent with `LootManager.Instance` in `LootCommand.cs`.
- No new serialized fields were added, only local variables and standard Unity methods.
- Handled the `-count` flag by stripping the last argument if it matches before joining the rest for the search term.

[qwen3.5:27b on http://192.168.1.189:11434: 5098 prompt tokens, 1184 answer tokens, 48 tokens/s]