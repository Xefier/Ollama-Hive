// FILE: RollingStats.cs
using System;

namespace Xefier.Core.Stats
{
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
                throw new ArgumentOutOfRangeException(nameof(capacity));

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

                float min = _buffer[0];
                for (int i = 1; i < _count; i++)
                {
                    float v = _buffer[i];
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
                    throw new InvalidOperationException("RollingStats is empty.");

                float max = _buffer[0];
                for (int i = 1; i < _count; i++)
                {
                    float v = _buffer[i];
                    if (v > max)
                        max = v;
                }
                return max;
            }
        }

        public float Percentile(float p)
        {
            if (p < 0f || p > 1f)
                throw new ArgumentOutOfRangeException(nameof(p));
            if (_count == 0)
                throw new InvalidOperationException("RollingStats is empty.");

            Array.Copy(_buffer, _scratch, _count);
            Array.Sort(_scratch, 0, _count);

            int rank = (int)Math.Ceiling(p * _count);
            if (rank < 1) rank = 1;
            if (rank > _count) rank = _count;

            return _scratch[rank - 1];
        }

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
                _sum -= _buffer[_writeIndex];
                _buffer[_writeIndex] = value;
                _writeIndex++;
                if (_writeIndex == _capacity) _writeIndex = 0;
            }
            _sum += value;
        }

        public void Clear()
        {
            _writeIndex = 0;
            _count = 0;
            _sum = 0.0;
        }
    }
}
