// FILE: TileFindCommand.cs
using System;
using System.Collections.Generic;
using System.Text;
using DunGen;
using UnityEngine;

namespace ConsoleUtility
{
    /// <summary>
    /// Tile debugging. "tilefind" lists the generated level's tiles whose name contains a search term,
    /// showing each one's position and cull state (or just the count with -count).
    /// </summary>
    [AutoRegisterConsoleCommand]
    public class TileFindCommand : ConsoleCommandBase, IConsoleCommand
    {
        // Past this many matching tiles the per-tile lines stop; the total still covers them all.
        private const int MaxLines = 25;
        private const string CountOption = "-count";

        public string name => "tilefind";
        public string summary => "Find tiles in the generated level by name";

        // "\n" rather than a verbatim string, so a CRLF checkout doesn't carry '\r's into the console.
        public string help =>
            "Command: tilefind <name> [-count]\n" +
            "* <name>   : lists every tile whose name contains <name> (case-insensitive), one per line with\n" +
            "             position (whole metres) and cull state, up to " + MaxLines + " lines.\n" +
            "             Example: tilefind \"Big Tile\"\n" +
            "* -count   : prints only the total count line.\n" +
            "             Example: tilefind \"Big Tile\" -count";

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

            // Peel the trailing -count option off the end so a name with spaces stays intact.
            bool countOnly = false;
            int nameEnd = args.Length; // exclusive index
            if (args.Length >= 2 && IsKeyword(args[args.Length - 1], CountOption))
            {
                countOnly = true;
                nameEnd = args.Length - 1;
            }

            string term = JoinArgs(args, 1, nameEnd - 1);
            if (string.IsNullOrEmpty(term))
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

            var allTiles = dungeon.AllTiles;
            int total = allTiles.Count;
            int matches = 0;
            int culled = 0;
            var perTile = new StringBuilder();

            foreach (var tile in allTiles)
            {
                if (tile == null) continue;
                if (tile.name.IndexOf(term, StringComparison.OrdinalIgnoreCase) < 0) continue;

                matches++;
                bool isCulled = tile.IsCulled;
                if (isCulled) culled++;

                if (!countOnly && matches <= MaxLines)
                {
                    var p = tile.transform.position;
                    perTile.Append($"\n  {tile.name} ({Mathf.RoundToInt(p.x)}, {Mathf.RoundToInt(p.y)}, {Mathf.RoundToInt(p.z)}) {isCulled ? "culled" : "visible"}");
                }
            }

            var report = new StringBuilder();
            if (!countOnly)
            {
                report.Append(perTile);
                if (matches > MaxLines)
                    report.Append($"\n  ... and {matches - MaxLines} more");
            }

            report.Append((countOnly || matches > 0 || perTile.Length > 0) ? "\n" : "");
            report.Append($"{matches} of {total} tiles match '{term}' ({culled} culled)");

            Console.Log(name, report.ToString());
        }
    }
}
