// FILE: RollingStats.cs

// ReSharper disable CommentTypo
// ReSharper disable IdentifierTypo

using System;

namespace Xefier.Core.Stats
{
    /// <summary>
    /// Keeps statistics over the last <see cref="Capacity"/> float samples (a sliding window, e.g. frame times).
    /// Pure C#, no Unity. Add is O(1) and allocation-free; Min/Max/Percentile are O(n) over the window.
    /// </summary>
    public sealed class RollingStats
    {
        private readonly float[] _buffer;   // circular buffer of samples; oldest is at _head
        private readonly float[] _scratch;  // reused by Percentile so it allocates nothing after construction
        private int _head;                  // index of the oldest sample
        private int _count;                 // samples currently held (0 .. Capacity)
        private double _sum;                // running sum kept as a double: float drifts over millions of Adds

        /// <summary>Number of samples the window holds before the oldest drops out. At least 1.</summary>
        public int Capacity { get; }

        /// <summary>Number of samples currently held (0 when empty, up to <see cref="Capacity"/>).</summary>
        public int Count => _count;

        public RollingStats(int capacity)
        {
            if (capacity < 1)
                throw new ArgumentOutOfRangeException(nameof(capacity), "capacity must be >= 1");

            Capacity = capacity;
            _buffer = new float[capacity];
            _scratch = new float[capacity];
        }

        /// <summary>Adds a sample. O(1), no allocation. Once full, the oldest sample drops out.</summary>
        public void Add(float value)
        {
            if (_count == _capacity())
            {
                // Full: overwrite the oldest slot and advance it, so it becomes the newest.
                _buffer[_head] = value;
                _head++;
                if (_head == _capacity()) _head = 0;
            }
            else
            {
                int index = _head + _count;
                if (index >= _capacity()) index -= _capacity();
                _buffer[index] = value;
                _count++;
            }

            _sum += value;
        }

        public float Mean
        {
            get
            {
                CheckNotEmpty();
                return (float)(_sum / _count);
            }
        }

        public float Min
        {
            get
            {
                CheckNotEmpty();
                return Extreme(true);
            }
        }

        public float Max
        {
            get
            {
                CheckNotEmpty();
                return Extreme(false);
            }
        }

        /// <summary>
        /// The <paramref name="p"/> quantile of the current window, nearest-rank method: rank = ceil(p * Count),
        /// clamped to [1, Count], and the rank-th smallest sample. p must be in [0, 1].
        /// </summary>
        public float Percentile(float p)
        {
            if (p < 0f || p > 1f)
                throw new ArgumentOutOfRangeException(nameof(p), "p must be in [0, 1]");
            CheckNotEmpty();

            // ceil(p * Count), clamped: p = 0 gives the smallest, p = 1 the largest.
            int rank = (int)Math.Ceiling(p * _count);
            if (rank < 1) rank = 1;
            if (rank > _count) rank = _count;

            // Sort a copy: Array.Sort on a float range is in-place, so no allocation (the scratch array is ours).
            CopyWindow(_scratch);
            Array.Sort(_scratch, 0, _count);
            return _scratch[rank - 1];
        }

        public void Clear()
        {
            _head = 0;
            _count = 0;
            _sum = 0d;
        }

        // The smallest (min) or largest (max) sample in the window. O(n).
        private float Extreme(bool smallest)
        {
            float result = _buffer[_head];
            for (int i = 1; i < _count; i++)
            {
                float v = At(i);
                if (smallest ? v < result : v > result) result = v;
            }

            return result;
        }

        // Copies the current window in order into dest[0..Count).
        private void CopyWindow(float[] dest)
        {
            for (int i = 0; i < _count; i++)
                dest[i] = At(i);
        }

        // The sample Count-1 newer than the oldest.
        private float At(int offset)
        {
            int index = _head + offset;
            if (index >= _capacity()) index -= _capacity();
            return _buffer[index];
        }

        private void CheckNotEmpty()
        {
            if (_count == 0)
                throw new InvalidOperationException("RollingStats is empty");
        }

        private int _capacity() => Capacity;
    }
}
