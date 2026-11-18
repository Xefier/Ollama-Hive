```csharp
// FILE: RollingStats.cs
using System;

namespace Xefier.Core.Stats
{
    /// <summary>
    /// Statistics over the last <see cref="Capacity"/> float samples in a sliding window (e.g. frame times).
    /// The mean is O(1); Min, Max and Percentile scan the window. Not thread-safe.
    /// </summary>
    public sealed class RollingStats
    {
        private readonly float[] _values;
        private readonly float[] _scratch; // Percentile's sort space, preallocated so nothing allocates after construction
        private int _next; // slot the next Add writes to
        private int _count;
        private double _sum; // double: a float sum drifts noticeably after a few thousand Adds

        public RollingStats(int capacity)
        {
            if (capacity < 1)
                throw new ArgumentOutOfRangeException(nameof(capacity), "Capacity must be at least 1");

            _values = new float[capacity];
            _scratch = new float[capacity];
        }

        public int Count => _count;

        public int Capacity => _values.Length;

        public void Add(float value)
        {
            int slot = _next;
            if (_count == _values.Length)
                _sum -= _values[slot]; // the sample being replaced drops out of the window

            _values[slot] = value;
            _sum += value;
            if (_count < _values.Length)
                _count++;
            _next = slot + 1 == _values.Length ? 0 : slot + 1;
        }

        public void Clear()
        {
            _next = 0;
            _count = 0;
            _sum = 0.0;
        }

        public float Mean
        {
            get
            {
                if (_count == 0)
                    throw new InvalidOperationException("RollingStats has no samples");
                return (float)(_sum / _count);
            }
        }

        public float Min
        {
            get
            {
                ScanMinMax(out float min, out _);
                return min;
            }
        }

        public float Max
        {
            get
            {
                ScanMinMax(out _, out float max);
                return max;
            }
        }

        /// <summary>
        /// Nearest-rank percentile, p in [0, 1]: the rank-th smallest sample with rank = clamp(ceil(p * Count), 1, Count).
        /// </summary>
        public float Percentile(float p)
        {
            if (p < 0f || p > 1f)
                throw new ArgumentOutOfRangeException(nameof(p), "Percentile must be in [0, 1]");
            if (_count == 0)
                throw new InvalidOperationException("RollingStats has no samples");

            CopyWindow(_scratch);
            Array.Sort(_scratch, 0, _count);

            // double so the product stays exact for large windows
            int rank = (int)Math.Ceil(p * (double)_count);
            if (rank < 1)
                rank = 1;
            else if (rank > _count)
                rank = _count;

            return _scratch[rank - 1];
        }

        private void ScanMinMax(out float min, out float max)
        {
            if (_count == 0)
                throw new InvalidOperationException("RollingStats has no samples");

            // The window is [next, next + head) followed by [0, tail) in the ring
            int tail = Math.Min(_next, _count);
            int head = _count - tail;

            float mn = float.PositiveInfinity;
            float mx = float.NegativeInfinity;

            for (int i = 0; i < head; i++)
            {
                float v = _values[_next + i];
                if (v < mn) mn = v;
                if (v > mx) mx = v;
            }

            for (int i = 0; i < tail; i++)
            {
                float v = _values[i];
                if (v < mn) mn = v;
                if (v > mx) mx = v;
            }

            min = mn;
            max = mx;
        }

        // Copies the window, oldest to newest, into dest[0..Count)
        private void CopyWindow(float[] dest)
        {
            int tail = Math.Min(_next, _count);
            Array.Copy(_values, _next, dest, 0, _count - tail);
            Array.Copy(_values, 0, dest, _count - tail, tail);
        }
    }
}
```

- No project files were given to match style against, so I used conventional C# matching the requested namespace; adjust if your house style differs (e.g. expression-bodied members).
- `Percentile` uses `Array.Sort` on a preallocated scratch prefix (O(n log n)); if you need O(n) there, a QuickSelect can replace it.
- Percentile rank uses double for the `p * Count` product to avoid float rounding at large windows.

[qwen3.8-unity:27b on http://192.168.1.189:11434: 839 prompt tokens, 2936 answer tokens, 68 tokens/s]