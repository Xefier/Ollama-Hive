using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using DunGen;
using LiminalLabs.LootSystem;
using UnityEngine;

namespace ConsoleUtility
{
    /// <summary>
    /// Loot debugging. "loot find" counts the spawned loot whose entry name contains a search term and marks each item
    /// on screen through walls (FindHighlighter), coloured by whether its tile is culled.
    /// </summary>
    [AutoRegisterConsoleCommand]
    public class LootCommand : ConsoleCommandBase, IConsoleCommand
    {
        // Past this many matching entries the per-entry lines stop; the totals still cover them all.
        private const int MaxEntryLines = 25;

        public string name => "loot";
        public string summary => "Loot: find spawned loot by entry name";

        // "\n" rather than a verbatim string, so a CRLF checkout doesn't carry '\r's into the console.
        public string help =>
            "Command: loot <find|clear>\n" +
            "* find <name> : counts the spawned loot whose entry name contains <name>, in any case (loot find book finds\n" +
            "                Collectable_Book), split into culled / unculled / total, and marks each item on screen\n" +
            "                through walls: filled green = its tile is unculled, hollow red = its tile is culled\n" +
            "* clear       : removes the markers";

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

            switch (args[0].ToLowerInvariant())
            {
                case "find":
                    if (args.Length < 2)
                        LogHelp(this);
                    else
                        Find(JoinArgs(args, 1));
                    break;

                case "clear":
                    FindHighlighter.Clear(name);
                    Console.Log(name, "Loot markers cleared");
                    break;

                default:
                    LogHelp(this);
                    break;
            }
        }

        private class EntryMatch
        {
            public LootEntry Entry;
            public int Culled;
            public int Unculled;
            public readonly Dictionary<string, int> ByRecord = new();
        }

        private void Find(string term)
        {
            var manager = LootManager.Instance;
            if (manager == null || manager.Database == null)
            {
                Console.Log(name, "No LootManager with a database in this scene", LogType.Warning);
                return;
            }

            // Entries the term names, even with nothing spawned, so "0 in level" is told apart from "no such entry".
            var matches = new Dictionary<LootEntry, EntryMatch>();
            foreach (var entry in manager.Database.entries)
            {
                if (entry != null && Matches(entry, term))
                    matches[entry] = new EntryMatch { Entry = entry };
            }

            var targets = new List<FindHighlighter.Target>();
            foreach (var volume in manager.Volumes)
            {
                if (volume == null) continue;

                foreach (var loot in volume.SpawnedLoot)
                {
                    if (loot == null || !volume.TryGetSpawnedEntry(loot, out var entry, out var record)) continue;
                    // A variant's own name can match too (loot find book_03).
                    if (!matches.TryGetValue(entry, out var match))
                    {
                        if (!Matches(record, term)) continue;
                        match = matches[entry] = new EntryMatch { Entry = entry };
                    }

                    // Loot is reparented onto its tile once the tile has spawned, and sits under its volume (under the
                    // tile) before that, so the parent tile is the one the culler hides it with.
                    var tile = loot.GetComponentInParent<Tile>() ?? volume.GetTile();
                    if (tile != null && tile.IsCulled) match.Culled++;
                    else match.Unculled++;

                    string recordName = record != null ? record.name : entry.name;
                    match.ByRecord.TryGetValue(recordName, out int count);
                    match.ByRecord[recordName] = count + 1;

                    targets.Add(new FindHighlighter.Target(loot, tile, recordName));
                }
            }

            if (matches.Count == 0)
            {
                FindHighlighter.Clear(name);
                Console.Log(name, $"No loot entry name contains '{term}'", LogType.Warning);
                return;
            }

            int culled = matches.Values.Sum(m => m.Culled);
            int unculled = matches.Values.Sum(m => m.Unculled);

            var report = new StringBuilder();
            report.Append($"'{term}': {culled + unculled} in level ({unculled} unculled, {culled} culled)");
            if (manager.IsSpawning) report.Append(" - loot is still spawning, the count may grow");

            // Spawned entries first, most first; then the ones that match but have nothing in the level.
            var ordered = matches.Values.OrderByDescending(m => m.Culled + m.Unculled).ThenBy(m => m.Entry.name).ToList();
            for (int i = 0; i < ordered.Count && i < MaxEntryLines; i++)
            {
                var m = ordered[i];
                report.Append($"\n  {m.Entry.name}: {m.Culled + m.Unculled} ({m.Unculled} unculled, {m.Culled} culled)");
                // Break a group down by variant, unless only the entry itself spawned.
                if (m.ByRecord.Count > 1 || (m.ByRecord.Count == 1 && !m.ByRecord.ContainsKey(m.Entry.name)))
                    report.Append(" - ").Append(string.Join(", ", m.ByRecord.OrderBy(r => r.Key).Select(r => $"{r.Key} x{r.Value}")));
            }
            if (ordered.Count > MaxEntryLines)
                report.Append($"\n  ... and {ordered.Count - MaxEntryLines} more entries; narrow the name to list them");

            Console.Log(name, report.ToString());

            if (targets.Count > 0)
                FindHighlighter.Show(name, term, targets);
            else
                FindHighlighter.Clear(name);
        }

        private static bool Matches(LootEntryBase record, string term)
        {
            return record != null
                   && (record.name.IndexOf(term, StringComparison.OrdinalIgnoreCase) >= 0
                       || (record.HasPrefab && record.PrefabName.IndexOf(term, StringComparison.OrdinalIgnoreCase) >= 0));
        }
    }
}
