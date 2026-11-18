using System;
using System.Collections.Generic;
using System.Text;
using DunGen;
using UnityEngine;

namespace ConsoleUtility
{
    /// <summary>
    /// Tile debugging. "tilefind" lists the tiles of the current generated level whose name contains a search term.
    /// </summary>
    [AutoRegisterConsoleCommand]
    public class TileFindCommand : ConsoleCommandBase, IConsoleCommand
    {
        // Past this many matching tiles the per-tile lines stop; the total still covers them all.
        private const int MaxLines = 25;

        public string name => "tilefind";
        public string summary => "Finds the tiles of the current level by name";

        // "\n" rather than a verbatim string, so a CRLF checkout doesn't carry '\r's into the console.
        public string help =>
            "Command: tilefind <name> [-count]\n" +
            "* <name>      : every tile whose name contains <name>, in any case, one line each (name, position in\n" +
            "               metres, culled / visible), at most 25, then the total\n" +
            "* <name> -count : only the total line\n" +
            "Examples: tilefind book\n" +
            "          tilefind Big Tile\n" +
            "          tilefind Big Tile -count";

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

            // -count is a trailing option after a name that may itself have spaces, so peel it off the end first.
            bool countOnly = false;
            int nameLength = args.Length;
            if (nameLength > 1 && IsKeyword(args[nameLength - 1], "-count"))
            {
                countOnly = true;
                nameLength--;
            }

            string term = JoinArgs(args, 0, nameLength);
            if (term.Length == 0)
            {
                LogHelp(this);
                return;
            }

            var dungeon = DungeonGenerator.Instance?.CurrentDungeon;
            if (dungeon == null)
            {
                Console.Log(name, "No generated level", LogType.Warning);
                return;
            }

            var tiles = dungeon.AllTiles;
            int total = tiles.Count, matches = 0, culled = 0, shown = 0;
            var lines = new StringBuilder();
            foreach (var tile in tiles)
            {
                if (tile == null || tile.name.IndexOf(term, StringComparison.OrdinalIgnoreCase) < 0) continue;

                matches++;
                if (tile.IsCulled) culled++;

                if (countOnly) continue;
                if (shown >= MaxLines) continue;

                if (shown > 0) lines.Append('\n');
                var p = tile.transform.position;
                lines.Append(tile.name).Append("  (").Append(Mathf.Round(p.x)).Append(", ").Append(Mathf.Round(p.y))
                    .Append(", ").Append(Mathf.Round(p.z)).Append(")  ").Append(tile.IsCulled ? "culled" : "visible");
                shown++;
            }

            var report = new StringBuilder();
            if (!countOnly)
            {
                if (lines.Length > 0)
                {
                    report.Append(lines);
                    if (matches > MaxLines)
                        report.Append($"\n... and {matches - MaxLines} more; narrow the name to list them");
                    report.Append('\n');
                }
            }
            report.Append($"{matches} of {total} tiles match '{term}' ({culled} culled)");

            Console.Log(name, report.ToString());
        }
    }
}
