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
    /// term, with world position and cull state.
    /// </summary>
    [AutoRegisterConsoleCommand]
    public class TileFindCommand : ConsoleCommandBase, IConsoleCommand
    {
        private const int MaxLines = 25;

        public string name => "tilefind";

        public string summary => "Find tiles by name in the current level";

        public string help =>
            "Command: tilefind <text> [-count]\n" +
            "* <text>      : lists tiles whose name contains <text> (case-insensitive), one per line with world\n" +
            "                position and cull state (tilefind Big Tile finds a tile named \"Big Tile 3\")\n" +
            "* -count      : prints only the total match line, no per-tile listing";

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

            // Peel the trailing -count option before joining the name (the name itself may contain spaces).
            bool countOnly = false;
            int nameCount = args.Length;
            if (args.Length >= 2 && IsKeyword(args[args.Length - 1], "-count"))
            {
                countOnly = true;
                nameCount = args.Length - 1;
            }

            string term = JoinArgs(args, 0, nameCount);
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
            int total = 0;
            int culled = 0;
            int matched = 0;

            var report = new StringBuilder();
            int lines = 0;

            foreach (var tile in allTiles)
            {
                if (tile == null) continue;
                total++;

                if (tile.name.IndexOf(term, StringComparison.OrdinalIgnoreCase) < 0)
                    continue;

                matched++;
                if (tile.IsCulled) culled++;

                if (!countOnly && lines < MaxLines)
                {
                    if (lines > 0) report.Append('\n');
                    Vector3 pos = tile.transform.position;
                    report.Append(tile.name)
                          .Append("  (").Append(Mathf.RoundToInt(pos.x)).Append(", ")
                          .Append(Mathf.RoundToInt(pos.y)).Append(", ")
                          .Append(Mathf.RoundToInt(pos.z)).Append(")  ")
                          .Append(tile.IsCulled ? "culled" : "visible");
                    lines++;
                }
            }

            if (matched > MaxLines && !countOnly)
                report.Append("\n... and ").Append(matched - MaxLines).Append(" more");

            if (report.Length > 0)
                report.Append('\n');

            report.Append(matched).Append(" of ").Append(total).Append(" tiles match '")
                  .Append(term).Append("' (").Append(culled).Append(" culled)");

            Console.Log(name, report.ToString());
        }
    }
}
```

- `Dungeon.AllTiles` is documented as `IReadOnlyCollection<Tile>`; I assume it is non-null when `CurrentDungeon` is non-null (no null check on the collection itself, matching how `LootManager.Volumes` is iterated).
- The `-count` flag is only peeled when at least two args are present, so a lone `tilefind -count` is treated as a literal search term (edge case unlikely in practice).
- I used `Mathf.RoundToInt` for whole-metre display; if the project prefers `System.Math.Round` cast to int the change is trivial.
- Followed the LootCommand pattern of `IsEnabled => true` with a TODO, since this is a debug/developer tool.

[qwen3.8:27b-q8_0 on http://192.168.1.232:11434: 5057 prompt tokens, 6691 answer tokens, 52 tokens/s]