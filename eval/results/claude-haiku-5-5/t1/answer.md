```csharp
// FILE: RollingStats.cs
using System;

namespace Xefier.Core.Stats
{
    // Statistics over the last Capacity samples. Everything is preallocated in the constructor so Add and
    // Percentile never allocate, which matters when a caller samples every frame.
    public sealed class RollingStats
    {
        private readonly float[] _samples;
        private readonly float[] _scratch;
        private int _next;
        private int _count;

        // Kept as a double: a float running sum drifts visibly over millions of Adds.
        private double _sum;

        public RollingStats(int capacity)
        {
            if (capacity < 1)
                throw new ArgumentOutOfRangeException(nameof(capacity), capacity, "Capacity must be at least 1.");

            _samples = new float[capacity];
            _scratch = new float[capacity];
        }

        public int Count => _count;
        public int Capacity => _samples.Length;

        public float Mean
        {
            get
            {
                RequireSamples();
                return (float)(_sum / _count);
            }
        }

        public float Min
        {
            get
            {
                RequireSamples();
                float min = _samples[0];
                for (int i = 1; i < _count; i++)
                {
                    if (_samples[i] < min)
                        min = _samples[i];
                }
                return min;
            }
        }

        public float Max
        {
            get
            {
                RequireSamples();
                float max = _samples[0];
                for (int i = 1; i < _count; i++)
                {
                    if (_samples[i] > max)
                        max = _samples[i];
                }
                return max;
            }
        }

        public void Add(float value)
        {
            // Once full, the slot about to be overwritten is the oldest sample: take it out of the sum first.
            if (_count == _samples.Length)
                _sum -= _samples[_next];
            else
                _count++;

            _samples[_next] = value;
            _sum += value;

            _next++;
            if (_next == _samples.Length)
                _next = 0;
        }

        // Nearest-rank on the current window. Sorts a copy in the preallocated scratch array, so the
        // samples keep their ring order for Add.
        public float Percentile(float p)
        {
            if (!(p >= 0f && p <= 1f))
                throw new ArgumentOutOfRangeException(nameof(p), p, "Percentile must be in [0, 1].");

            RequireSamples();

            Array.Copy(_samples, _scratch, _count);
            Array.Sort<float>(_scratch, 0, _count);

            int rank = (int)Math.Ceiling((double)p * _count);
            if (rank < 1)
                rank = 1;
            else if (rank > _count)
                rank = _count;

            return _scratch[rank - 1];
        }

        public void Clear()
        {
            _next = 0;
            _count = 0;
            _sum = 0.0;
        }

        private void RequireSamples()
        {
            if (_count == 0)
                throw new InvalidOperationException("RollingStats has no samples.");
        }
    }
}
```

- Written from the task text only; no project files were given, so nothing in the project was checked or compiled.
- Min, Max and Percentile on an empty window throw InvalidOperationException, as specified; Percentile checks p before the emptiness check, so an out-of-range p on an empty window throws ArgumentOutOfRangeException.
- NaN samples are not filtered: Min and Max would ignore or propagate them depending on comparison order, and the sort in Percentile places them unpredictably. The spec does not say what to do, so I left it.
- Percentile sorts a copy of the window on every call, so it is O(n log n) per call, not O(1). The window is copied into the scratch array of the constructor's size, so it allocates nothing.
- Clear resets the counters and the sum but does not zero the sample arrays, which is fine because Count bounds every read.
