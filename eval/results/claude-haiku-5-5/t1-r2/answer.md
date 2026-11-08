```csharp
// FILE: RollingStats.cs
using System;

namespace Xefier.Core.Stats
{
    /// <summary>
    /// Statistics over the last <see cref="Capacity"/> samples, kept in a ring buffer so that
    /// Add never allocates or shifts the window. Mean is O(1) from a running sum; Min, Max and
    /// Percentile walk the window.
    /// </summary>
    public sealed class RollingStats
    {
        readonly float[] samples;
        // Scratch copy of the window, sorted by Percentile. Allocated once here so Percentile
        // never allocates.
        readonly float[] scratch;
        readonly int capacity;

        int head;   // index the next Add writes to
        int count;
        // Kept as double: adding and removing millions of floats would drift a float sum.
        double sum;

        public RollingStats(int capacity)
        {
            if (capacity < 1)
                throw new ArgumentOutOfRangeException(nameof(capacity), capacity, "Capacity must be at least 1.");

            this.capacity = capacity;
            samples = new float[capacity];
            scratch = new float[capacity];
        }

        public int Count => count;

        public int Capacity => capacity;

        public float Mean
        {
            get
            {
                RequireSamples();
                return (float)(sum / count);
            }
        }

        public float Min
        {
            get
            {
                RequireSamples();
                float min = float.MaxValue;
                int start = OldestIndex();
                for (int i = 0; i < count; i++)
                {
                    float v = samples[(start + i) % capacity];
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
                RequireSamples();
                float max = float.MinValue;
                int start = OldestIndex();
                for (int i = 0; i < count; i++)
                {
                    float v = samples[(start + i) % capacity];
                    if (v > max)
                        max = v;
                }
                return max;
            }
        }

        public void Add(float value)
        {
            if (count == capacity)
                sum -= samples[head];
            else
                count++;

            samples[head] = value;
            sum += value;
            head = (head + 1) % capacity;
        }

        /// <summary>
        /// Nearest-rank percentile of the current window. p is in [0, 1].
        /// </summary>
        public float Percentile(float p)
        {
            // Written as a negated comparison so that NaN is rejected too.
            if (!(p >= 0f && p <= 1f))
                throw new ArgumentOutOfRangeException(nameof(p), p, "Percentile must be in [0, 1].");
            RequireSamples();

            int start = OldestIndex();
            for (int i = 0; i < count; i++)
                scratch[i] = samples[(start + i) % capacity];

            Array.Sort(scratch, 0, count);

            int rank = (int)Math.Ceiling(p * count);
            if (rank < 1)
                rank = 1;
            else if (rank > count)
                rank = count;

            return scratch[rank - 1];
        }

        public void Clear()
        {
            head = 0;
            count = 0;
            sum = 0.0;
        }

        // Index of the oldest sample in the ring buffer. Works whether or not the buffer is full,
        // because head is always count samples past the oldest one (mod capacity).
        int OldestIndex()
        {
            return (head - count + capacity) % capacity;
        }

        void RequireSamples()
        {
            if (count == 0)
                throw new InvalidOperationException("RollingStats has no samples.");
        }
    }
}
```

- Brace style and comment density are assumed from general C# conventions; no other project file in the task was visible to match against, so the Allman braces and XML doc comments are a guess.
- `files.txt` for t1 does not exist, so no extra files were read beyond rules.txt and prompt.txt.
- Percentile sorts a copy in a preallocated scratch array with the generic `Array.Sort<T>(T[], int, int)`; I did not verify it is allocation-free on the target runtime.
- Min and Max seed with `float.MaxValue` / `float.MinValue`; a window containing only `+Infinity` or `-Infinity` values would not be handled exactly.
- No NaN handling in Add or Mean; a NaN sample will poison the running sum for the rest of the window's life.
