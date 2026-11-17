// FILE: RollingStats.cs

using System;

namespace Xefier.Core.Stats
{
    /// <summary>
    /// Sliding-window statistics over the last N float samples (e.g. frame times).
    /// </summary>
    public sealed class RollingStats
    {
        private readonly float[] _buffer;
        private readonly float[] _scratch;
        private readonly int _capacity;

        private int _start;
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
                    throw new InvalidOperationException("Cannot compute Mean on an empty window.");
                return (float)(_sum / _count);
            }
        }

        public float Min
        {
            get
            {
                if (_count == 0)
                    throw new InvalidOperationException("Cannot compute Min on an empty window.");

                float min = _buffer[_start];
                for (int i = 1; i < _count; i++)
                {
                    float v = _buffer[(_start + i) % _capacity];
                    if (v < min)
                        min = v;
                }
                return min;
            }
        }

        public float Max
        {
            get
            {
                if (_count == 0)
                    throw new InvalidOperationException("Cannot compute Max on an empty window.");

                float max = _buffer[_start];
                for (int i = 1; i < _count; i++)
                {
                    float v = _buffer[(_start + i) % _capacity];
                    if (v > max)
                        max = v;
                }
                return max;
            }
        }

        public void Add(float value)
        {
            if (_count < _capacity)
            {
                int idx = (_start + _count) % _capacity;
                _buffer[idx] = value;
                _sum += value;
                _count++;
            }
            else
            {
                // Window is full: oldest sample (at _start) drops out.
                _sum -= _buffer[_start];
                _buffer[_start] = value;
                _sum += value;
                _start = (_start + 1) % _capacity;
            }
        }

        public float Percentile(float p)
        {
            if (p < 0f || p > 1f)
                throw new ArgumentOutOfRangeException(nameof(p), "Percentile must be in [0, 1].");
            if (_count == 0)
                throw new InvalidOperationException("Cannot compute Percentile on an empty window.");

            // Copy the current window into the preallocated scratch buffer.
            for (int i = 0; i < _count; i++)
                _scratch[i] = _buffer[(_start + i) % _capacity];

            Array.Sort(_scratch, 0, _count);

            // Nearest-rank: rank = ceil(p * n), clamped to [1, n].
            int rank = (int)Math.Ceiling(p * _count);
            if (rank < 1)
                rank = 1;
            if (rank > _count)
                rank = _count;

            return _scratch[rank - 1];
        }

        public void Clear()
        {
            _start = 0;
            _count = 0;
            _sum = 0.0;
        }
    }
}
