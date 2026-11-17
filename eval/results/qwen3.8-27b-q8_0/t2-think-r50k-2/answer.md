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
    /// Tile debugging. "tilefind" lists the tiles of the current generated level whose name contains a search
    /// term, showing each tile's position and cull state; "-count" prints only the total line.
    /// </summary>
    [AutoRegisterConsoleCommand]
    public class TileFindCommand : ConsoleCommandBase, IConsoleCommand
    {
        // Past this many matching tiles the per-tile lines stop; the total still covers them all.
        private const int MaxLines = 25;

        public string name => "tilefind";
        public string summary => "Find tiles in the current level by name";

        // "\n" rather than a verbatim string, so a CRLF checkout doesn't carry '\r's into the console.
        public string help =>
            "Command: tilefind <text> [-count]\n" +
            "* <text>      : lists every tile whose name contains <text> (case-insensitive), showing its world\n" +
            "               position (whole metres) and cull state (tilefind Big Tile)\n" +
            "* -count      : trailing option, logs only the total line (tilefind Big Tile -count)";

        public IEnumerable<Console.Alias> aliases { get { yield break; } }

        // Debug command, always enabled (same policy as LootCommand).
        protected override bool IsEnabled(string[] args) => true;

        protected override void ExecuteImpl(string[] args)
        {
            if (args.Length == 0)
            {
                LogHelp(this);
                return;
            }

            // -count is a trailing option after a name that may contain spaces, so peel it off before joining.
            bool countOnly = false;
            int nameEnd = args.Length;
            if (args.Length >= 3 && IsKeyword(args[args.Length - 1], "-count"))
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
            if (dungeon == null || dungeon.AllTiles == null)
            {
                Console.Log(name, "No generated level", LogType.Warning);
                return;
            }

            var allTiles = dungeon.AllTiles;
            int total = allTiles.Count;
            int matches = 0;
            int culled = 0;

            if (countOnly)
            {
                foreach (var tile in allTiles)
                {
                    if (tile == null) continue;
                    if (tile.name.IndexOf(term, StringComparison.OrdinalIgnoreCase) < 0) continue;

                    matches++;
                    if (tile.IsCulled) culled++;
                }

                Console.Log(name, $"{matches} of {total} tiles match '{term}' ({culled} culled)");
                return;
            }

            var report = new StringBuilder();
            int printed = 0;

            foreach (var tile in allTiles)
            {
                if (tile == null) continue;
                if (tile.name.IndexOf(term, StringComparison.OrdinalIgnoreCase) < 0) continue;

                matches++;
                if (tile.IsCulled) culled++;

                if (printed < MaxLines)
                {
                    if (printed > 0) report.Append('\n');
                    var pos = tile.transform.position;
                    report.Append("  ")
                          .Append(tile.name)
                          .Append(" (")
                          .Append(Mathf.RoundToInt(pos.x))
                          .Append(", ")
                          .Append(Mathf.RoundToInt(pos.y))
                          .Append(", ")
                          .Append(Mathf.RoundToInt(pos.z))
                          .Append(") ")
                          .Append(tile.IsCulled ? "culled" : "visible");
                    printed++;
                }
            }

            if (matches > MaxLines)
                report.Append($"\n  ... and {matches - MaxLines} more");

            report.Append($"\n{matches} of {total} tiles match '{term}' ({culled} culled)");

            Console.Log(name, report.ToString());
        }
    }
}
```

- Assumed `Tile.name` is the `GameObject.name` inherited from `MonoBehaviour` (the requirement says "GameObject name contains <text>"); no separate name property was needed.
- `Dungeon.AllTiles` could theoretically be non-null but empty; treated the same as a valid level (0 tiles match).
- The `-count` keyword match is case-insensitive via the inherited `IsKeyword` helper, consistent with other console commands.
- Did not add a `using` for `ConsoleUtility` since the file already lives in that namespace.
- The per-tile line format is `  <name> (x, y, z) culled|visible` — no explicit unit label since the spec says "whole metres".

[qwen3.8:27b-q8_0 on http://192.168.1.232:11434: 5057 prompt tokens, 5242 answer tokens, 52 tokens/s]