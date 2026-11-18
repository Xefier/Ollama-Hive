```csharp
// FILE: RollingStats.cs

using System;

namespace Xefier.Core.Stats
{
    /// <summary>
    /// Sliding window of the last <see cref="Capacity"/> float samples (e.g. frame times). Once full, the oldest
    /// sample drops out on every <see cref="Add"/>.
    /// </summary>
    public sealed class RollingStats
    {
        private readonly float[] _values;
        private readonly float[] _scratch; // reused by Percentile so it allocates only once
        private int _head; // buffer slot for the next Add; when full, the oldest sample sits here
        private int _count;
        private double _sum; // float drifts over millions of Adds

        public RollingStats(int capacity)
        {
            if (capacity < 1)
                throw new ArgumentOutOfRangeException(nameof(capacity), capacity, "capacity must be >= 1.");

            _values = new float[capacity];
            _scratch = new float[capacity];
            _head = 0;
            _count = 0;
            _sum = 0.0;
        }

        public int Capacity => _values.Length;

        public int Count => _count;

        public float Mean
        {
            get
            {
                ThrowIfEmpty();
                return (float)(_sum / _count);
            }
        }

        public float Min
        {
            get
            {
                ThrowIfEmpty();
                float min = ValueAt(0);
                for (int i = 1; i < _count; i++)
                {
                    float v = ValueAt(i);
                    if (v < min) min = v;
                }

                return min;
            }
        }

        public float Max
        {
            get
            {
                ThrowIfEmpty();
                float max = ValueAt(0);
                for (int i = 1; i < _count; i++)
                {
                    float v = ValueAt(i);
                    if (v > max) max = v;
                }

                return max;
            }
        }

        /// <summary>
        /// The nearest-rank percentile: the <c>rank</c>-th smallest sample, where <c>rank = ceil(p * Count)</c>
        /// clamped to <c>[1, Count]</c>.
        /// </summary>
        public float Percentile(float p)
        {
            if (p < 0f || p > 1f)
                throw new ArgumentOutOfRangeException(nameof(p), p, "p must be in [0, 1].");
            ThrowIfEmpty();

            int rank = (int)Math.Ceiling(p * _count);
            if (rank < 1) rank = 1;
            if (rank > _count) rank = _count;

            CopyWindow(_scratch, _count);
            Array.Sort(_scratch, 0, _count); // in-place for a primitive array, so no allocation
            return _scratch[rank - 1];
        }

        public void Add(float value)
        {
            if (_count < _values.Length)
            {
                _values[_head] = value;
                _count++;
            }
            else
            {
                // Full: the slot about to be overwritten holds the oldest sample, which drops out.
                _sum -= _values[_head];
                _values[_head] = value;
            }

            _head++;
            if (_head == _values.Length) _head = 0;
            _sum += value;
        }

        public void Clear()
        {
            _head = 0;
            _count = 0;
            _sum = 0.0;
        }

        /// <summary>Value at logical index <paramref name="logical"/> (0 = oldest, newest = <see cref="Count"/> - 1).</summary>
        private float ValueAt(int logical)
        {
            // Not full yet: the buffer starts at 0. Full: it starts at the oldest sample, which sits at _head.
            int index = _count < _values.Length ? logical : _head + logical;
            if (index >= _values.Length) index -= _values.Length;
            return _values[index];
        }

        // Copies the window oldest-to-newest, avoiding the modulo on every element.
        private void CopyWindow(float[] destination, int count)
        {
            if (_count < _values.Length)
            {
                for (int i = 0; i < count; i++) destination[i] = _values[i];
            }
            else
            {
                int index = _head;
                for (int i = 0; i < count; i++)
                {
                    destination[i] = _values[index];
                    index++;
                    if (index == _values.Length) index = 0;
                }
            }
        }

        private void ThrowIfEmpty()
        {
            if (_count == 0)
                throw new InvalidOperationException("The window is empty.");
        }
    }
}
```

- I kept `Count`/`Capacity` as read-only `int` properties rather than public fields (matching the `int Count` reading).
- `Clear()` does not zero the backing array: `Count == 0` marks it empty and all reads throw, so stale values are never seen.
- `Percentile` validates `p` first (`ArgumentOutOfRangeException`), then the empty check (`InvalidOperationException`); `Mean`/`Min`/`Max` only do the empty check.
- Nearest-rank `p * Count` is computed in `float`, exactly as written in the spec.
- No surrounding file was provided, so comment density is a sensible default; nothing here touches Unity, so none of the project's logging/console/perf rules apply.

[qwen3.8-unity:27b on http://192.168.1.182:11434: 839 prompt tokens, 6422 answer tokens, 31 tokens/s]