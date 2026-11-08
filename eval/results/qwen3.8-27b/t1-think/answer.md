```csharp
// FILE: RollingStats.cs
using System;

namespace Xefier.Core.Stats
{
    /// <summary>
    /// Fixed-capacity sliding-window statistics over float samples (e.g. frame times).
    /// Thread-safety is not provided; call from a single thread.
    /// </summary>
    public sealed class RollingStats
    {
        private readonly float[] _buffer;
        private readonly float[] _scratch; // preallocated for Percentile sort
        private readonly int _capacity;
        private int _writeIndex;
        private int _count;
        private double _sum; // double to avoid drift over millions of Adds

        public RollingStats(int capacity)
        {
            if (capacity < 1)
                throw new ArgumentOutOfRangeException(nameof(capacity), "Capacity must be at least 1.");

            _capacity = capacity;
            _buffer = new float[capacity];
            _scratch = new float[capacity];
        }

        public int Capacity => _capacity;
        public int Count => _count;

        public float Mean
        {
            get
            {
                if (_count == 0)
                    throw new InvalidOperationException("RollingStats window is empty.");
                return (float)(_sum / _count);
            }
        }

        public float Min
        {
            get
            {
                if (_count == 0)
                    throw new InvalidOperationException("RollingStats window is empty.");

                float min = _buffer[_writeIndex];
                for (int i = 1; i < _count; i++)
                {
                    int idx = _writeIndex + i;
                    if (idx >= _capacity) idx -= _capacity;
                    if (_buffer[idx] < min) min = _buffer[idx];
                }
                return min;
            }
        }

        public float Max
        {
            get
            {
                if (_count == 0)
                    throw new InvalidOperationException("RollingStats window is empty.");

                float max = _buffer[_writeIndex];
                for (int i = 1; i < _count; i++)
                {
                    int idx = _writeIndex + i;
                    if (idx >= _capacity) idx -= _capacity;
                    if (_buffer[idx] > max) max = _buffer[idx];
                }
                return max;
            }
        }

        /// <summary>
        /// Adds a sample. When the window is full the oldest sample is evicted.
        /// O(1), no heap allocation.
        /// </summary>
        public void Add(float value)
        {
            if (_count < _capacity)
            {
                _buffer[_writeIndex] = value;
                _writeIndex++;
                if (_writeIndex == _capacity) _writeIndex = 0;
                _count++;
            }
            else
            {
                // Evict oldest (currently at _writeIndex)
                _sum -= _buffer[_writeIndex];
                _buffer[_writeIndex] = value;
                _writeIndex++;
                if (_writeIndex == _capacity) _writeIndex = 0;
            }

            _sum += value;
        }

        /// <summary>
        /// Nearest-rank percentile: rank = ceil(p * Count), clamped to [1, Count].
        /// Uses a preallocated scratch buffer; no allocation after construction.
        /// </summary>
        public float Percentile(float p)
        {
            if (p < 0f || p > 1f)
                throw new ArgumentOutOfRangeException(nameof(p), "p must be in [0, 1].");
            if (_count == 0)
                throw new InvalidOperationException("RollingStats window is empty.");

            // Copy the window in chronological order into the scratch buffer.
            for (int i = 0; i < _count; i++)
            {
                int idx = _writeIndex + i;
                if (idx >= _capacity) idx -= _capacity;
                _scratch[i] = _buffer[idx];
            }

            // In-place introsort – no heap allocation.
            Array.Sort(_scratch, 0, _count);

            int rank = (int)Math.Ceiling((double)p * (double)_count);
            if (rank < 1) rank = 1;
            if (rank > _count) rank = _count;

            return _scratch[rank - 1];
        }

        /// <summary>Resets the window so Count is 0 and all statistics throw.</summary>
        public void Clear()
        {
            _writeIndex = 0;
            _count = 0;
            _sum = 0.0;
        }
    }
}
```

- `Min`/`Max` initialise from the first element (index `_writeIndex`) rather than `float.MaxValue`/`MinValue` to avoid edge-case issues with `NaN`; if NaN samples are expected you may want an explicit `float.IsNaN` guard — I assumed they are not.
- `Percentile` uses `Array.Sort` which is in-place introsort (recursive stack frames only, no heap/GC allocation), satisfying the "no allocation after construction" constraint.
- The circular-buffer index wrap uses a single `if` comparison instead of `%` to keep `Add` branch-predictable and allocation-free.
- No project-specific APIs were needed; only `System`, `Array`, and `Math` from the .NET standard library are used.

[qwen3.8:27b on http://192.168.1.189:11434: 839 prompt tokens, 3415 answer tokens, 121 tokens/s]