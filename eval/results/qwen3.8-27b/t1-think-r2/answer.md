```csharp
// FILE: RollingStats.cs

using System;

namespace Xefier.Core.Stats
{
    /// <summary>
    /// Sliding-window statistics over the last N float samples.
    /// Thread-unsafe by design; call from a single thread.
    /// </summary>
    public sealed class RollingStats
    {
        private readonly float[] _buffer;
        private readonly float[] _scratch; // preallocated so Percentile never allocates
        private readonly int _capacity;

        private int _head;   // index of the oldest element (next write slot)
        private int _count;  // number of valid samples (0..capacity)
        private double _sum; // running sum kept as double to limit float drift

        public RollingStats(int capacity)
        {
            if (capacity < 1)
                throw new ArgumentOutOfRangeException(nameof(capacity), "Capacity must be at least 1.");

            _capacity = capacity;
            _buffer = new float[capacity];
            _scratch = new float[capacity];
        }

        public int Count => _count;
        public int Capacity => _capacity;

        // ── Mutation ──────────────────────────────────────────────────────────

        public void Add(float value)
        {
            if (_count < _capacity)
            {
                _buffer[_head] = value;
                _sum += value;
                _head++;
                if (_head == _capacity) _head = 0;
                _count++;
            }
            else
            {
                // Window is full: evict the oldest sample before overwriting.
                _sum -= _buffer[_head];
                _buffer[_head] = value;
                _sum += value;
                _head++;
                if (_head == _capacity) _head = 0;
            }
        }

        public void Clear()
        {
            _head = 0;
            _count = 0;
            _sum = 0.0;
        }

        // ── Queries ───────────────────────────────────────────────────────────

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
                float min = _buffer[_head];
                int idx = _head + 1;
                if (idx == _capacity) idx = 0;

                for (int i = 1; i < _count; i++)
                {
                    float v = _buffer[idx];
                    if (v < min) min = v;
                    idx++;
                    if (idx == _capacity) idx = 0;
                }
                return min;
            }
        }

        public float Max
        {
            get
            {
                ThrowIfEmpty();
                float max = _buffer[_head];
                int idx = _head + 1;
                if (idx == _capacity) idx = 0;

                for (int i = 1; i < _count; i++)
                {
                    float v = _buffer[idx];
                    if (v > max) max = v;
                    idx++;
                    if (idx == _capacity) idx = 0;
                }
                return max;
            }
        }

        /// <summary>
        /// Nearest-rank percentile: rank = ceil(p * count), clamped to [1, count];
        /// result is the rank-th smallest sample in the current window.
        /// </summary>
        public float Percentile(float p)
        {
            if (p < 0f || p > 1f)
                throw new ArgumentOutOfRangeException(nameof(p), "Percentile must be in [0, 1].");
            ThrowIfEmpty();

            int rank = (int)Math.Ceiling((double)p * _count);
            if (rank < 1) rank = 1;
            if (rank > _count) rank = _count;

            // Copy the circular window into the preallocated scratch buffer, then sort.
            CopyWindowToScratch();
            Array.Sort(_scratch, 0, _count);
            return _scratch[rank - 1];
        }

        // ── Helpers ───────────────────────────────────────────────────────────

        private void CopyWindowToScratch()
        {
            int idx = _head;
            for (int i = 0; i < _count; i++)
            {
                _scratch[i] = _buffer[idx];
                idx++;
                if (idx == _capacity) idx = 0;
            }
        }

        private static void ThrowIfEmpty()
        {
            // Callers pass nothing; we need instance state. Inline the check instead.
        }
    }
}
```

Wait — I made an error: `ThrowIfEmpty()` is static but needs instance state. Let me fix that. I'll make it an instance method that checks `_count`.

```csharp
// FILE: RollingStats.cs

using System;

namespace Xefier.Core.Stats
{
    /// <summary>
    /// Sliding-window statistics over the last N float samples (e.g. frame times).
    /// Thread-unsafe by design; call from a single thread.
    /// </summary>
    public sealed class RollingStats
    {
        private readonly float[] _buffer;
        private readonly float[] _scratch; // preallocated so Percentile never allocates at runtime
        private readonly int _capacity;

        private int _head;   // index of the oldest element (next write slot)
        private int _count;  // number of valid samples (0 .. capacity)
        private double _sum; // running sum kept as double to limit float drift over many Adds

        public RollingStats(int capacity)
        {
            if (capacity < 1)
                throw new ArgumentOutOfRangeException(nameof(capacity), "Capacity must be at least 1.");

            _capacity = capacity;
            _buffer = new float[capacity];
            _scratch = new float[capacity];
        }

        public int Count => _count;
        public int Capacity => _capacity;

        // ── Mutation ──────────────────────────────────────────────────────────

        public void Add(float value)
        {
            if (_count < _capacity)
            {
                _buffer[_head] = value;
                _sum += value;
                _head++;
                if (_head == _capacity) _head = 0;
                _count++;
            }
            else
            {
                // Window is full: evict the oldest sample before overwriting.
                _sum -= _buffer[_head];
                _buffer[_head] = value;
                _sum += value;
                _head++;
                if (_head == _capacity) _head = 0;
            }
        }

        public void Clear()
        {
            _head = 0;
            _count = 0;
            _sum = 0.0;
        }

        // ── Queries ───────────────────────────────────────────────────────────

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
                float min = _buffer[_head];
                int idx = _head + 1;
                if (idx == _capacity) idx = 0;

                for (int i = 1; i < _count; i++)
                {
                    float v = _buffer[idx];
                    if (v < min) min = v;
                    idx++;
                    if (idx == _capacity) idx = 0;
                }
                return min;
            }
        }

        public float Max
        {
            get
            {
                ThrowIfEmpty();
                float max = _buffer[_head];
                int idx = _head + 1;
                if (idx == _capacity) idx = 0;

                for (int i = 1; i < _count; i++)
                {
                    float v = _buffer[idx];
                    if (v > max) max = v;
                    idx++;
                    if (idx == _capacity) idx = 0;
                }
                return max;
            }
        }

        /// <summary>
        /// Nearest-rank percentile: rank = ceil(p * count), clamped to [1, count];
        /// returns the rank-th smallest sample in the current window.
        /// </summary>
        public float Percentile(float p)
        {
            if (p < 0f || p > 1f)
                throw new ArgumentOutOfRangeException(nameof(p), "Percentile must be in [0, 1].");
            ThrowIfEmpty();

            int rank = (int)Math.Ceiling((double)p * _count);
            if (rank < 1) rank = 1;
            if (rank > _count) rank = _count;

            // Copy the circular window into the preallocated scratch buffer, then sort.
            CopyWindowToScratch();
            Array.Sort(_scratch, 0, _count);
            return _scratch[rank - 1];
        }

        // ── Helpers ───────────────────────────────────────────────────────────

        private void CopyWindowToScratch()
        {
            int idx = _head;
            for (int i = 0; i < _count; i++)
            {
                _scratch[i] = _buffer[idx];
                idx++;
                if (idx == _capacity) idx = 0;
            }
        }

        private void ThrowIfEmpty()
        {
            if (_count == 0)
                throw new InvalidOperationException("Cannot compute statistics on an empty window.");
        }
    }
}
```

- `Percentile` is O(n log n) due to `Array.Sort` on the scratch copy; the spec only requires "nearest-rank method" and no post-construction allocation, which is satisfied.
- I used a circular buffer with a "next-write = oldest" convention so the eviction in `Add` is a single array read before overwrite (O(1), zero allocations).
- `Clear()` does not zero the `_buffer` contents; stale floats past `_count` are never read by any public member.
- The class is intentionally not thread-safe; no locks are used. If you need cross-thread access, wrap calls externally.

[qwen3.8:27b on http://192.168.1.189:11434: 839 prompt tokens, 4784 answer tokens, 128 tokens/s]