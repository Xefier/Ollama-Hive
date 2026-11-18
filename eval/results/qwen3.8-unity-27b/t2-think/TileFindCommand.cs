// FILE: TileFindCommand.cs
using System;
using System.Collections.Generic;
using System.Text;
using DunGen;
using UnityEngine;

namespace ConsoleUtility
{
    /// <summary>
    /// Tile searching. "tilefind" lists the tiles of the current generated level whose name contains a search term,
    /// with their position and whether they are culled, so a level's layout can be read from the console.
    /// </summary>
    [AutoRegisterConsoleCommand]
    public class TileFindCommand : ConsoleCommandBase, IConsoleCommand
    {
        // Past this many matching tiles the per-tile lines stop; the totals still cover them all.
        private const int MaxLines = 25;

        public string name => "tilefind";
        public string summary => "Lists tiles of the current level whose name contains a search term";

        // "\n" rather than a verbatim string, so a CRLF checkout doesn't carry '\r's into the console.
        public string help =>
            "Command: tilefind <text> [-count]\n" +
            "* <text>    : lists every tile of the current generated level whose name contains <text>, in any case\n" +
            "             (tilefind Big lists Big Tile), one line each with its position and culled / visible,\n" +
            "             then a total (tilefind Big Tile)\n" +
            "* -count    : the total line only (tilefind Big Tile -count)";

        public IEnumerable<Console.Alias> aliases { get { yield break; } }

        protected override void ExecuteImpl(string[] args)
        {
            if (args.Length == 0)
            {
                LogHelp(this);
                return;
            }

            // A trailing -count asks for the total only, after a name that may have spaces.
            bool countOnly = false;
            int end = args.Length;
            if (args[end - 1].Equals("-count", StringComparison.OrdinalIgnoreCase))
            {
                countOnly = true;
                end--;
            }

            string term = JoinArgs(args, 0, end);
            if (term.Length == 0)
            {
                LogHelp(this);
                return;
            }

            Find(term, countOnly);
        }

        private static void Find(string term, bool countOnly)
        {
            var tiles = DungeonGenerator.Instance?.CurrentDungeon?.AllTiles;
            if (tiles == null)
            {
                Console.Log(name, "No generated level", LogType.Warning);
                return;
            }

            int total = tiles.Count;
            int culled = 0;
            int matches = 0;
            var lines = new List<string>(MaxLines);

            foreach (var tile in tiles)
            {
                if (tile == null) continue;

                string tileName = tile.name;
                if (tileName.IndexOf(term, StringComparison.OrdinalIgnoreCase) < 0) continue;

                matches++;
                bool isCulled = tile.IsCulled;
                if (isCulled) culled++;

                if (lines.Count < MaxLines)
                {
                    var pos = tile.transform.position;
                    lines.Add($"  {tileName} ({Mathf.RoundToInt(pos.x)}, {Mathf.RoundToInt(pos.y)}, {Mathf.RoundToInt(pos.z)}) {(isCulled ? "culled" : "visible")}");
                }
            }

            string totalLine = $"{matches} of {total} tiles match '{term}' ({culled} culled)";

            if (countOnly)
            {
                Console.Log(name, totalLine);
                return;
            }

            var report = new StringBuilder();
            for (int i = 0; i < lines.Count; i++)
            {
                report.Append(lines[i]);
                if (i + 1 < lines.Count) report.Append('\n');
            }

            if (matches > MaxLines)
                report.Append($"\n  ... and {matches - MaxLines} more");

            report.Append($"\n{totalLine}");

            Console.Log(name, report.ToString());
        }
    }
}
