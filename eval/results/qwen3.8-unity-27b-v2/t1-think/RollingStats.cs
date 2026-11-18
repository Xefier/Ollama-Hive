// FILE: RollingStats.cs
using System;

namespace Xefier.Core.Stats
{
    /// <summary>
    /// Keeps statistics over the last <see cref="Capacity"/> float samples in a sliding window (e.g. frame times).
    /// </summary>
    public sealed class RollingStats
    {
        private readonly int _capacity;
        private readonly float[] _values;
        private readonly float[] _scratch; // reused by Percentile, so nothing allocates after construction

        private int _head; // where the next Add goes; the oldest sample once full
        private int _count;
        // A double, not a float: a float sum drifts measurably after millions of Adds
        private double _sum;

        public RollingStats(int capacity)
        {
            if (capacity < 1)
            {
                throw new ArgumentOutOfRangeException(nameof(capacity), capacity, "capacity must be >= 1");
            }

            _capacity = capacity;
            _values = new float[capacity];
            _scratch = new float[capacity];
        }

        public int Count => _count;

        public int Capacity => _capacity;

        /// <summary>
        /// Records a sample in O(1). Once full, the oldest sample drops out.
        /// </summary>
        public void Add(float value)
        {
            int index = _head;
            if (_count == _capacity)
            {
                // Full: the sample at _head is the oldest and is being dropped
                _sum -= _values[index];
            }

            _values[index] = value;
            _sum += value;

            _head++;
            if (_head == _capacity)
            {
                _head = 0;
            }

            if (_count < _capacity)
            {
                _count++;
            }
        }

        /// <summary>The mean, O(1).</summary>
        public float Mean
        {
            get
            {
                EnsureNotEmpty();
                return (float)(_sum / _count);
            }
        }

        public float Min
        {
            get
            {
                EnsureNotEmpty();
                return Scan(true);
            }
        }

        public float Max
        {
            get
            {
                EnsureNotEmpty();
                return Scan(false);
            }
        }

        /// <summary>
        /// The p-th percentile, 0 <= p <= 1, by the nearest-rank method: the rank-th smallest sample where
        /// rank = ceil(p * Count) clamped to [1, Count].
        /// </summary>
        public float Percentile(float p)
        {
            if (p < 0f || p > 1f)
            {
                throw new ArgumentOutOfRangeException(nameof(p), p, "p must be in [0, 1]");
            }

            EnsureNotEmpty();

            int rank = (int)Math.Ceiling(p * _count);
            if (rank < 1) rank = 1;
            if (rank > _count) rank = _count;

            int start = _head;
            for (int i = 0; i < _count; i++)
            {
                int index = start + i;
                if (index >= _capacity)
                {
                    index -= _capacity;
                }

                _scratch[i] = _values[index];
            }

            Array.Sort(_scratch, 0, _count);
            return _scratch[rank - 1];
        }

        public void Clear()
        {
            _head = 0;
            _count = 0;
            _sum = 0.0;
        }

        private float Scan(bool isMin)
        {
            int start = _head;
            float result = isMin ? float.MaxValue : float.MinValue;
            for (int i = 0; i < _count; i++)
            {
                int index = start + i;
                if (index >= _capacity)
                {
                    index -= _capacity;
                }

                float sample = _values[index];
                if (isMin ? sample < result : sample > result)
                {
                    result = sample;
                }
            }

            return result;
        }

        private void EnsureNotEmpty()
        {
            if (_count == 0)
            {
                throw new InvalidOperationException("The window is empty; Add at least one sample first");
            }
        }
    }
}
