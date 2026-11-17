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
        private int _head;
        private int _count;
        private double _sum;

        public RollingStats(int capacity)
        {
            if (capacity < 1)
                throw new ArgumentOutOfRangeException(nameof(capacity), "Capacity must be >= 1.");

            _capacity = capacity;
            _buffer = new float[capacity];
            _scratch = new float[capacity];
        }

        public int Count => _count;
        public int Capacity => _capacity;

        public void Add(float value)
        {
            if (_count == _capacity)
                _sum -= _buffer[_head];

            _buffer[_head] = value;
            _sum += value;
            _head = (_head + 1) % _capacity;

            if (_count < _capacity)
                _count++;
        }

        public float Mean
        {
            get
            {
                if (_count == 0)
                    throw new InvalidOperationException("RollingStats is empty.");
                return (float)(_sum / _count);
            }
        }

        public float Min
        {
            get
            {
                if (_count == 0)
                    throw new InvalidOperationException("RollingStats is empty.");

                int limit = _count < _capacity ? _count : _capacity;
                float min = _buffer[0];
                for (int i = 1; i < limit; i++)
                {
                    if (_buffer[i] < min)
                        min = _buffer[i];
                }
                return min;
            }
        }

        public float Max
        {
            get
            {
                if (_count == 0)
                    throw new InvalidOperationException("RollingStats is empty.");

                int limit = _count < _capacity ? _count : _capacity;
                float max = _buffer[0];
                for (int i = 1; i < limit; i++)
                {
                    if (_buffer[i] > max)
                        max = _buffer[i];
                }
                return max;
            }
        }

        public float Percentile(float p)
        {
            if (p < 0f || p > 1f)
                throw new ArgumentOutOfRangeException(nameof(p), "p must be in [0, 1].");
            if (_count == 0)
                throw new InvalidOperationException("RollingStats is empty.");

            int limit = _count < _capacity ? _count : _capacity;

            // Copy window into preallocated scratch, sort in-place (no heap alloc for float[]).
            Array.Copy(_buffer, _scratch, limit);
            Array.Sort(_scratch, 0, limit);

            int rank = (int)Math.Ceiling(p * (double)limit);
            if (rank < 1)
                rank = 1;
            else if (rank > limit)
                rank = limit;

            return _scratch[rank - 1];
        }

        public void Clear()
        {
            _head = 0;
            _count = 0;
            _sum = 0.0;
        }
    }
}
