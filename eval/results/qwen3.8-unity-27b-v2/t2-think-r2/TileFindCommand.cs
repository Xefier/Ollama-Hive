// FILE: TileFindCommand.cs
using System.Collections.Generic;
using System.Text;
using DunGen;
using UnityEngine;

namespace ConsoleUtility
{
    /// <summary>
    /// Tile debugging. "tilefind" lists the tiles of the current generated level whose names contain a search term,
    /// with their world position and whether they are culled.
    /// </summary>
    [AutoRegisterConsoleCommand]
    public class TileFindCommand : ConsoleCommandBase, IConsoleCommand
    {
        // Past this many matching tiles the per-tile lines stop; the total still covers them all.
        private const int MaxMatchLines = 25;

        public string name => "tilefind";
        public string summary => "Finds the tiles of the current level by name";

        // "\n" rather than a verbatim string, so a CRLF checkout doesn't carry '\r's into the console.
        public string help =>
            "Command: tilefind <name> [-count]\n" +
            "* <name>  : lists every tile of the current level whose name contains <name>, in any case, with its\n" +
            "            world position (whole metres) and whether it is culled; -count prints only the totals\n" +
            "* example : tilefind Big Tile, tilefind tile -count";

        public IEnumerable<Console.Alias> aliases { get { yield break; } }
        //TODO: Disable this before release
        protected override bool IsEnabled(string[] args) => true;


        protected override void ExecuteImpl(string[] args)
        {
            // -count is a trailing option that follows a name which may itself have spaces (Big Tile -count).
            int argCount = args.Length;
            bool countOnly = argCount > 1 && IsKeyword(args[argCount - 1], "-count");
            if (countOnly)
            {
                argCount--;
            }

            if (argCount == 1)
            {
                LogHelp(this);
                return;
            }

            string term = JoinArgs(args, 1, argCount - 1);

            var generator = DungeonGenerator.Instance;
            var dungeon = generator != null ? generator.CurrentDungeon : null;
            if (dungeon == null || dungeon.AllTiles == null)
            {
                Console.Log(name, "No generated level", LogType.Warning);
                return;
            }

            var tiles = dungeon.AllTiles;
            int total = tiles.Count;
            var matches = new List<Tile>();
            foreach (var tile in tiles)
            {
                if (tile != null && tile.gameObject.name.IndexOf(term, StringComparison.OrdinalIgnoreCase) >= 0)
                    matches.Add(tile);
            }

            int culled = 0;
            foreach (var tile in matches)
            {
                if (tile.IsCulled) culled++;
            }

            var report = new StringBuilder();
            if (!countOnly)
            {
                for (int i = 0; i < matches.Count && i < MaxMatchLines; i++)
                {
                    var tile = matches[i];
                    Vector3 p = tile.transform.position;
                    report.Append($"  {tile.gameObject.name} at ({Mathf.RoundToInt(p.x)}, {Mathf.RoundToInt(p.y)}, {Mathf.RoundToInt(p.z)}) ");
                    report.Append(tile.IsCulled ? "culled" : "visible");
                }
                if (matches.Count > MaxMatchLines)
                    report.Append($"\n  ... and {matches.Count - MaxMatchLines} more");
                if (matches.Count > 0)
                    report.Append('\n');
            }

            report.Append($"{matches.Count} of {total} tiles match '{term}' ({culled} culled)");
            Console.Log(name, report.ToString());
        }
    }
}
