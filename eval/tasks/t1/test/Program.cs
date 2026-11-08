using System; using System.Linq; using Xefier.Core.Stats;
int fails = 0;
void Check(bool ok, string what) { if (!ok) { fails++; Console.WriteLine("FAIL " + what); } }
void Throws<T>(Action a, string what) where T : Exception { try { a(); Check(false, what + " (no throw)"); } catch (T) { } catch (Exception e) { Check(false, what + " threw " + e.GetType().Name); } }
Throws<ArgumentOutOfRangeException>(() => new RollingStats(0), "capacity 0");
var s = new RollingStats(5);
Throws<InvalidOperationException>(() => { var _ = s.Mean; }, "empty mean");
Throws<InvalidOperationException>(() => { var _ = s.Min; }, "empty min");
Throws<InvalidOperationException>(() => { var _ = s.Max; }, "empty max");
Throws<InvalidOperationException>(() => s.Percentile(0.5f), "empty percentile");
s.Add(1);
Throws<ArgumentOutOfRangeException>(() => s.Percentile(1.1f), "p>1");
Throws<ArgumentOutOfRangeException>(() => s.Percentile(-0.1f), "p<0");
var rnd = new Random(7); var all = new System.Collections.Generic.List<float>();
var r = new RollingStats(37);
for (int i = 0; i < 1000; i++)
{
    float v = (float)(rnd.NextDouble() * 100 - 20); r.Add(v); all.Add(v);
    var w = all.Skip(Math.Max(0, all.Count - 37)).ToArray(); var sorted = w.OrderBy(x => x).ToArray();
    Check(r.Count == w.Length, $"count at {i}");
    Check(Math.Abs(r.Mean - w.Average()) < 1e-3, $"mean at {i}: {r.Mean} vs {w.Average()}");
    Check(r.Min == w.Min() && r.Max == w.Max(), $"min/max at {i}");
    foreach (var p in new[] { 0f, 0.01f, 0.25f, 0.5f, 0.9f, 0.99f, 1f })
    {
        int rank = Math.Clamp((int)Math.Ceiling(p * w.Length), 1, w.Length);
        Check(r.Percentile(p) == sorted[rank - 1], $"p{p} at {i}: {r.Percentile(p)} vs {sorted[rank - 1]}");
    }
}
// Percentile must not reorder the window: the oldest sample still drops out next
var o = new RollingStats(3); o.Add(3); o.Add(1); o.Add(2); o.Percentile(0.5f); o.Add(10);
Check(o.Min == 1 && Math.Abs(o.Mean - (1 + 2 + 10) / 3f) < 1e-4, "percentile disturbed window order");
o.Clear(); Check(o.Count == 0, "clear"); o.Add(4); Check(o.Mean == 4 && o.Max == 4, "after clear");
var d = new RollingStats(100); for (int i = 0; i < 10_000_000; i++) d.Add(0.1f + (i % 2) * 1000f);
Check(Math.Abs(d.Mean - 500.1f) < 0.01f, "drift: " + d.Mean);
long before = GC.GetAllocatedBytesForCurrentThread();
for (int i = 0; i < 100000; i++) { d.Add(i); d.Percentile(0.95f); }
long alloc = GC.GetAllocatedBytesForCurrentThread() - before;
Check(alloc == 0, "allocated " + alloc + " bytes in Add/Percentile");
Console.WriteLine(fails == 0 ? "ALL PASS" : fails + " failures");
