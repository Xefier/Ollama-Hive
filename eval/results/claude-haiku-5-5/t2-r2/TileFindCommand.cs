// FILE: TileFindCommand.cs
using System;
using System.Collections.Generic;
using DunGen;
using UnityEngine;

namespace ConsoleUtility
{
    /// <summary>
    /// Tile debugging. "tilefind" lists the tiles of the current generated level whose GameObject name contains a text,
    /// with their world position and whether the culler hides them.
    /// </summary>
    [AutoRegisterConsoleCommand]
    public class TileFindCommand : ConsoleCommandBase, IConsoleCommand
    {
        // Past this many matching tiles the per-tile lines stop; the totals still cover them all.
        private const int MaxTileLines = 25;

        public string name => "tilefind";
        public string summary => "Tiles: find tiles of the generated level by name";

        // "\n" rather than a verbatim string, so a CRLF checkout doesn't carry '\r's into the console.
        public string help =>
            "Command: tilefind <text> [-count]\n" +
            "* <text>        : lists the tiles whose name contains <text>, in any case (tilefind big finds Tile_PlayRooms_BigTile1),\n" +
            "                  with their world position and culled / visible, then the totals\n" +
            "* <text> -count : only the totals\n" +
            "Example: tilefind Big Tile";

        public IEnumerable<Console.Alias> aliases { get { yield break; } }

        protected override void ExecuteImpl(string[] args)
        {
            if (args.Length == 0)
            {
                LogHelp(this);
                return;
            }

            // -count is a trailing option, so it is peeled off before the name (which may contain spaces) is joined back
            bool countOnly = IsKeyword(args[args.Length - 1], "-count");
            int nameCount = countOnly ? args.Length - 1 : args.Length;

            if (nameCount == 0)
            {
                LogHelp(this);
                return;
            }

            Find(JoinArgs(args, 0, nameCount), countOnly);
        }

        private void Find(string text, bool countOnly)
        {
            var generator = DungeonGenerator.Instance;
            var dungeon = generator != null ? generator.CurrentDungeon : null;
            if (dungeon == null)
            {
                Console.Log(name, "No generated level", LogType.Warning);
                return;
            }

            var matches = new List<Tile>();
            int culled = 0;
            foreach (var tile in dungeon.AllTiles)
            {
                if (tile == null || tile.name.IndexOf(text, StringComparison.OrdinalIgnoreCase) < 0) continue;

                matches.Add(tile);
                if (tile.IsCulled) culled++;
            }

            if (!countOnly)
            {
                for (int i = 0; i < matches.Count && i < MaxTileLines; i++)
                {
                    var tile = matches[i];
                    Vector3 p = tile.transform.position;
                    string state = tile.IsCulled ? "culled" : "visible";
                    Console.Log(name, $"{tile.name} at ({Mathf.RoundToInt(p.x)}, {Mathf.RoundToInt(p.y)}, {Mathf.RoundToInt(p.z)}) - {state}");
                }

                if (matches.Count > MaxTileLines)
                    Console.Log(name, $"... and {matches.Count - MaxTileLines} more");
            }

            Console.Log(name, $"{matches.Count} of {dungeon.AllTiles.Count} tiles match '{text}' ({culled} culled)");
        }
    }
}
