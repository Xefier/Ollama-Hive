// FILE: TileFindCommand.cs
using System;
using System.Collections.Generic;
using System.Text;
using DunGen;
using UnityEngine;

namespace ConsoleUtility
{
    /// <summary>
    /// Tile debugging: lists tiles in the current generated level whose name contains a search term, with world
    /// position and cull state.
    /// </summary>
    [AutoRegisterConsoleCommand]
    public class TileFindCommand : ConsoleCommandBase, IConsoleCommand
    {
        // Past this many matching tiles the per-tile lines stop; the total still covers them all.
        private const int MaxTileLines = 25;

        public string name => "tilefind";
        public string summary => "Find tiles in the current level by name";

        // "\n" rather than a verbatim string, so a CRLF checkout doesn't carry '\r's into the console.
        public string help =>
            "Command: tilefind <text> [-count]\n" +
            "* <text>  : lists every tile whose name contains <text> (case-insensitive): name, world position\n" +
            "           (whole metres), culled or visible - up to 25 lines, then a total\n" +
            "  e.g. tilefind Big Tile\n" +
            "* -count  : prints only the total line (trailing option, after a name that may have spaces)\n" +
            "  e.g. tilefind Big Tile -count";

        public IEnumerable<Console.Alias> aliases { get { yield break; } }
        //TODO: Disable this before release
        protected override bool IsEnabled(string[] args) => true;

        protected override void ExecuteImpl(string[] args)
        {
            if (args.Length == 0)
            {
                LogHelp(this);
                return;
            }

            // -count is a trailing option after a name that may itself contain spaces, so peel it from the end.
            bool countOnly = false;
            int end = args.Length;
            if (end > 1 && IsKeyword(args[end - 1], "-count"))
            {
                countOnly = true;
                end--;
            }

            string term = JoinArgs(args, 0, end);
            if (string.IsNullOrEmpty(term))
            {
                LogHelp(this);
                return;
            }

            var generator = DungeonGenerator.Instance;
            if (generator == null || generator.CurrentDungeon == null)
            {
                Console.Log(name, "No generated level", LogType.Warning);
                return;
            }

            var allTiles = generator.CurrentDungeon.AllTiles;
            int total = allTiles.Count;
            int matches = 0;
            int culled = 0;
            int lines = 0;

            var report = new StringBuilder();

            foreach (var tile in allTiles)
            {
                if (tile == null) continue;
                if (tile.name.IndexOf(term, StringComparison.OrdinalIgnoreCase) < 0) continue;

                matches++;
                bool isCulled = tile.IsCulled;
                if (isCulled) culled++;

                if (!countOnly && lines < MaxTileLines)
                {
                    var pos = tile.transform.position;
                    report.Append(tile.name)
                          .Append("  (")
                          .Append(Mathf.RoundToInt(pos.x)).Append(", ")
                          .Append(Mathf.RoundToInt(pos.y)).Append(", ")
                          .Append(Mathf.RoundToInt(pos.z)).Append(")  ")
                          .Append(isCulled ? "culled" : "visible");
                    if (lines < matches - 1 || matches < MaxTileLines)
                        report.Append('\n');
                    lines++;
                }
            }

            if (!countOnly && matches > MaxTileLines)
            {
                if (lines > 0) report.Append('\n');
                report.Append($"... and {matches - MaxTileLines} more\n");
            }

            report.Append($"{matches} of {total} tiles match '{term}' ({culled} culled)");

            Console.Log(name, report.ToString());
        }
    }
}
