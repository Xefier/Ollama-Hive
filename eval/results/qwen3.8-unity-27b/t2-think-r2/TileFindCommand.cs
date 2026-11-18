// FILE: TileFindCommand.cs
using System;
using System.Collections.Generic;
using System.Text;
using DunGen;
using UnityEngine;

namespace ConsoleUtility
{
    /// <summary>
    /// Tile debugging. "tilefind" lists the tiles of the current generated level whose name contains a search term, with
    /// their world position and whether the culler has hidden them, to find out which tile a piece of loot or entity
    /// sits on and why it is (or is not) hidden.
    /// </summary>
    [AutoRegisterConsoleCommand]
    public class TileFindCommand : ConsoleCommandBase, IConsoleCommand
    {
        // Past this many matches the per-tile lines stop; the total still covers them all.
        private const int MaxLines = 25;

        public string name => "tilefind";
        public string summary => "Tiles: list the current level's tiles by name, with their culling";

        // "\n" rather than a verbatim string, so a CRLF checkout doesn't carry '\r's into the console.
        public string help =>
            "Command: tilefind <text> [-count]\n" +
            "* <text>  : every tile of the current generated level whose name contains <text>, in any case (tilefind Big Tile finds\n" +
            "            \"Big Tile 001\"), one line each with its name, world position in whole metres, and whether it is culled\n" +
            "* -count  : only the total line, after a name that may have spaces (tilefind Big Tile -count)";

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

            // -count is a trailing option after the name, which may itself have spaces, so peel it off the end first
            bool countOnly = IsKeyword(args[args.Length - 1], "-count");
            int nameWords = args.Length - (countOnly ? 1 : 0);
            if (nameWords == 0)
            {
                LogHelp(this);
                return;
            }

            Find(JoinArgs(args, 0, nameWords), countOnly);
        }

        private void Find(string term, bool countOnly)
        {
            var generator = DungeonGenerator.Instance;
            var dungeon = generator != null ? generator.CurrentDungeon : null;
            IReadOnlyCollection<Tile> tiles = dungeon != null ? dungeon.AllTiles : null;
            if (tiles == null)
            {
                Console.Log(name, "No generated level", LogType.Warning);
                return;
            }

            int all = tiles.Count;
            int matches = 0, culled = 0, shown = 0;
            var report = new StringBuilder();

            foreach (var tile in tiles)
            {
                if (tile == null) continue;
                string tileName = tile.name;
                if (tileName.IndexOf(term, StringComparison.OrdinalIgnoreCase) < 0) continue;

                matches++;
                bool isCulled = tile.IsCulled;
                if (isCulled) culled++;

                if (!countOnly && shown < MaxLines)
                {
                    shown++;
                    Vector3 p = tile.transform.position;
                    report.Append("\n  ").Append(tileName)
                          .Append("  (").Append(Mathf.RoundToInt(p.x)).Append(", ").Append(Mathf.RoundToInt(p.y)).Append(", ").Append(Mathf.RoundToInt(p.z)).Append(")  ")
                          .Append(isCulled ? "culled" : "visible");
                }
            }

            if (!countOnly && matches > MaxLines)
                report.Append("\n  ... and ").Append(matches - MaxLines).Append(" more");

            report.Append("\n  ").Append(matches).Append(" of ").Append(all).Append(" tiles match '").Append(term).Append("' (").Append(culled).Append(" culled)");

            Console.Log(name, report.ToString());
        }
    }
}
