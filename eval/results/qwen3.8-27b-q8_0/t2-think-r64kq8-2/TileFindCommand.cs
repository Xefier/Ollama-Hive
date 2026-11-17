// FILE: TileFindCommand.cs
using System;
using System.Collections.Generic;
using System.Text;
using DunGen;
using UnityEngine;

namespace ConsoleUtility
{
    /// <summary>
    /// Tile debugging. "tilefind" lists the tiles of the current generated level whose name contains a search
    /// term, with world position and cull state, so you can confirm a tile exists and whether the culler hid it.
    /// </summary>
    [AutoRegisterConsoleCommand]
    public class TileFindCommand : ConsoleCommandBase, IConsoleCommand
    {
        // Past this many matching tiles the per-tile lines stop; the totals still cover them all.
        private const int MaxTileLines = 25;

        public string name => "tilefind";
        public string summary => "Find tiles by name in the current level";

        public string help =>
            "Command: tilefind <text> [-count]\n" +
            "* <text>       : lists every tile whose name contains <text> (case-insensitive), one per line with\n" +
            "                 world position (whole metres) and cull state; at most 25 lines, then \"... and N more\"\n" +
            "* -count       : only the total line, e.g. tilefind Big Tile -count\n" +
            "\n" +
            "Example: tilefind Big Tile";

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

            // Peel the trailing -count option before joining the (possibly multi-word) name.
            bool countOnly = false;
            int nameCount = args.Length;
            if (nameCount > 0 && IsKeyword(args[nameCount - 1], "-count"))
            {
                countOnly = true;
                nameCount--;
            }

            string term = JoinArgs(args, 0, nameCount);
            if (term.Length == 0)
            {
                LogHelp(this);
                return;
            }

            Find(term, countOnly);
        }

        private void Find(string term, bool countOnly)
        {
            var dungeon = DungeonGenerator.Instance?.CurrentDungeon;
            if (dungeon == null)
            {
                Console.Log(name, "No generated level", LogType.Warning);
                return;
            }

            var allTiles = dungeon.AllTiles;
            int matchCount = 0;
            int culledCount = 0;
            var report = new StringBuilder();
            int linesWritten = 0;

            foreach (var tile in allTiles)
            {
                if (tile == null) continue;
                if (tile.name.IndexOf(term, StringComparison.OrdinalIgnoreCase) < 0) continue;

                matchCount++;
                if (tile.IsCulled) culledCount++;

                if (!countOnly && linesWritten < MaxTileLines)
                {
                    if (linesWritten > 0) report.Append('\n');
                    var pos = tile.transform.position;
                    report.Append($"  {tile.name} ({Mathf.RoundToInt(pos.x)}, {Mathf.RoundToInt(pos.y)}, {Mathf.RoundToInt(pos.z)}) - {(tile.IsCulled ? "culled" : "visible")}");
                    linesWritten++;
                }
            }

            if (matchCount == 0)
            {
                Console.Log(name, $"No tiles contain '{term}'", LogType.Warning);
                return;
            }

            string total = $"{matchCount} of {allTiles.Count} tiles match '{term}' ({culledCount} culled)";

            if (countOnly)
            {
                Console.Log(name, total);
                return;
            }

            if (matchCount > MaxTileLines)
                report.Append($"\n  ... and {matchCount - MaxTileLines} more");
            report.Append($"\n{total}");

            Console.Log(name, report.ToString());
        }
    }
}
