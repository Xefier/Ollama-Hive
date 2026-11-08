```csharp
// FILE: TileFindCommand.cs
using System;
using System.Collections.Generic;
using System.Text;
using DunGen;
using UnityEngine;

namespace ConsoleUtility
{
    /// <summary>
    /// Tile debugging. "tilefind" lists the tiles of the current generated level whose GameObject name contains
    /// a search term, with position and cull state.
    /// </summary>
    [AutoRegisterConsoleCommand]
    public class TileFindCommand : ConsoleCommandBase, IConsoleCommand
    {
        private const int MaxLines = 25;

        public string name => "tilefind";

        public string summary => "Find tiles by name in the current generated level";

        // "\n" rather than a verbatim string, so a CRLF checkout doesn't carry '\r's into the console.
        public string help =>
            "Command: tilefind <text> [-count]\n" +
            "* <text>        : lists tiles whose name contains <text> (case-insensitive), up to 25 lines, each\n" +
            "                showing name, world position (whole metres), culled or visible\n" +
            "                (tilefind Big Tile finds Big_Tile_03)\n" +
            "* <text> -count : prints only the total match line";

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

            // -count is a trailing option after a name that may itself contain spaces, so peel it off the end
            // before joining the rest as the search term.
            bool countOnly = false;
            int argEnd = args.Length;
            if (argEnd > 1 && IsKeyword(args[argEnd - 1], "-count"))
            {
                countOnly = true;
                argEnd--;
            }

            if (argEnd < 2)
            {
                LogHelp(this);
                return;
            }

            Find(JoinArgs(args, 1, argEnd - 1), countOnly);
        }

        private void Find(string term, bool countOnly)
        {
            var gen = DungeonGenerator.Instance;
            var dungeon = gen?.CurrentDungeon;
            if (dungeon == null)
            {
                Console.Log(name, "No generated level", LogType.Warning);
                return;
            }

            var allTiles = dungeon.AllTiles;
            int total = allTiles.Count;
            int matchCount = 0;
            int culledCount = 0;
            int shown = 0;
            var lines = countOnly ? null : new StringBuilder();

            foreach (var tile in allTiles)
            {
                if (tile == null) continue;
                if (tile.name.IndexOf(term, StringComparison.OrdinalIgnoreCase) < 0) continue;

                matchCount++;
                bool culled = tile.IsCulled;
                if (culled) culledCount++;

                if (lines != null && shown < MaxLines)
                {
                    var p = tile.transform.position;
                    lines.Append("  ").Append(tile.name)
                         .Append(" (").Append(Mathf.RoundToInt(p.x)).Append(", ")
                         .Append(Mathf.RoundToInt(p.y)).Append(", ")
                         .Append(Mathf.RoundToInt(p.z)).Append(") ")
                         .Append(culled ? "culled" : "visible")
                         .Append('\n');
                    shown++;
                }
            }

            if (matchCount == 0)
            {
                Console.Log(name, $"No tile name contains '{term}'", LogType.Warning);
                return;
            }

            if (lines == null)
            {
                Console.Log(name, $"{matchCount} of {total} tiles match '{term}' ({culledCount} culled)");
            }
            else
            {
                if (matchCount > MaxLines)
                    lines.Append("  ... and ").Append(matchCount - MaxLines).Append(" more\n");
                lines.Append(matchCount).Append(" of ").Append(total)
                     .Append(" tiles match '").Append(term).Append("' (")
                     .Append(culledCount).Append(" culled)");
                Console.Log(name, lines.ToString());
            }
        }
    }
}
```

- `Tile.name` is the `MonoBehaviour`/`GameObject` name (inherited); assumed it is searchable as required.
- `Dungeon.AllTiles` is typed as `IReadOnlyCollection<Tile>` per the prompt; the `foreach` over it is allocation-free at the iterator level (the collection is pre-built by DunGen).
- The `IsEnabled` override returning `true` mirrors `LootCommand`'s "TODO: Disable before release" pattern; adjust if you want password-gating.
- `-count` is matched with exact string equality (via `IsKeyword`); a `+count` or `COUNT` form would not be recognised—let me know if you need that.
- I did not add a `using` for `System.Linq` because no LINQ is needed here.

[qwen3.8:27b on http://192.168.1.189:11434: 5072 prompt tokens, 4561 answer tokens, 126 tokens/s]