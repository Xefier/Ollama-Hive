// FILE: RollingStats.cs
using System;

namespace Xefier.Core.Stats
{
    /// <summary>
    /// Sliding-window statistics over the last N float samples (e.g. frame times).
    /// All queries are allocation-free after construction.
    /// </summary>
    public sealed class RollingStats
    {
        private readonly float[] _buffer;
        private readonly float[] _scratch;
        private readonly int _capacity;
        private int _writeIndex;
        private int _count;
        private double _sum;

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

                float min = float.MaxValue;
                int start = _count < _capacity ? 0 : _writeIndex;

                for (int i = 0; i < _count; i++)
                {
                    float v = _buffer[(start + i) % _capacity];
                    if (v < min) min = v;
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

                float max = float.MinValue;
                int start = _count < _capacity ? 0 : _writeIndex;

                for (int i = 0; i < _count; i++)
                {
                    float v = _buffer[(start + i) % _capacity];
                    if (v > max) max = v;
                }

                return max;
            }
        }

        /// <summary>
        /// Nearest-rank percentile: rank = ceil(p * Count), clamped to [1, Count].
        /// </summary>
        public float Percentile(float p)
        {
            if (p < 0f || p > 1f)
                throw new ArgumentOutOfRangeException(nameof(p), "Percentile must be in [0, 1].");
            if (_count == 0)
                throw new InvalidOperationException("RollingStats window is empty.");

            CopyWindowToScratch();
            Array.Sort(_scratch, 0, _count);

            int rank = (int)Math.Ceiling(p * (double)_count);
            if (rank < 1) rank = 1;
            if (rank > _count) rank = _count;

            return _scratch[rank - 1];
        }

        public void Clear()
        {
            _writeIndex = 0;
            _count = 0;
            _sum = 0.0;
            Array.Clear(_buffer, 0, _capacity);
        }

        // O(1) amortised; no allocation.
        public void Add(float value)
        {
            if (_count < _capacity)
            {
                _buffer[_writeIndex] = value;
                _writeIndex = (_writeIndex + 1) % _capacity;
                _count++;
                _sum += value;
            }
            else
            {
                // Overwrite the oldest sample (at _writeIndex).
                _sum -= _buffer[_writeIndex];
                _buffer[_writeIndex] = value;
                _sum += value;
                _writeIndex = (_writeIndex + 1) % _capacity;
            }
        }

        // Copies the logical window (oldest→newest) into _scratch[0..count-1] for sorting.
        private void CopyWindowToScratch()
        {
            if (_count < _capacity)
            {
                Array.Copy(_buffer, 0, _scratch, 0, _count);
            }
            else
            {
                // Full buffer: logical start is _writeIndex; the tail wraps to index 0.
                int firstPart = _capacity - _writeIndex;
                Array.Copy(_buffer, _writeIndex, _scratch, 0, firstPart);
                Array.Copy(_buffer, 0, _scratch, firstPart, _writeIndex);
            }
        }
    }
}
