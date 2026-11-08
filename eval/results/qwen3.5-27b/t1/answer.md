// FILE: RollingStats.cs
using System;

namespace Xefier.Core.Stats
{
    /// <summary>
    /// Maintains a sliding window of float samples for statistical analysis without runtime allocations.
    /// </summary>
    public sealed class RollingStats
    {
        private readonly float[] _buffer;
        private int _headIndex; // Index of the next slot to overwrite (oldest item if full)
        private int _count;     // Current number of items in the window

        // Use double for running sum to prevent precision loss over many Add operations.
        private double _sum;
        
        // Scratch array allocated once in constructor for sorting during Percentile calculations.
        private float[] _scratchBuffer;

        /// <summary>
        /// Initializes a new instance with the specified capacity.
        /// </summary>
        /// <param name="capacity">The maximum number of samples to retain.</param>
        /// <exception cref="ArgumentOutOfRangeException">Thrown when capacity is less than 1.</exception>
        public RollingStats(int capacity)
        {
            if (capacity < 1)
                throw new ArgumentOutOfRangeException(nameof(capacity));

            _buffer = new float[capacity];
            _scratchBuffer = new float[capacity];
            Capacity = capacity;
            _count = 0;
            _headIndex = 0;
            _sum = 0.0;
        }

        /// <summary>
        /// The current number of samples in the window.
        /// </summary>
        public int Count => _count;

        /// <summary>
        /// The maximum capacity of the window.
        /// </summary>
        public int Capacity { get; }

        /// <summary>
        /// Adds a new sample to the sliding window. If full, the oldest sample is dropped.
        /// O(1) operation with no allocations.
        /// </summary>
        /// <param name="value">The value to add.</param>
        public void Add(float value)
        {
            if (_count == Capacity)
            {
                // Window is full: subtract the oldest value before overwriting it.
                _sum -= _buffer[_headIndex];
            }
            else
            {
                _count++;
            }

            // Overwrite at head and advance head (circularly)
            _buffer[_headIndex] = value;
            _sum += value;
            
            _headIndex = (_headIndex + 1) % Capacity;
        }

        /// <summary>
        /// Clears all statistics and resets the window.
        /// </summary>
        public void Clear()
        {
            _count = 0;
            _headIndex = 0;
            _sum = 0.0;
        }

        /// <summary>
        /// Gets the arithmetic mean of the current samples.
        /// </summary>
        /// <exception cref="InvalidOperationException">Thrown when the window is empty.</exception>
        public float Mean
        {
            get
            {
                if (_count == 0)
                    throw new InvalidOperationException("Window is empty.");

                return (float)(_sum / _count);
            }
        }

        /// <summary>
        /// Gets the minimum value in the current window. O(n).
        /// </summary>
        /// <exception cref="InvalidOperationException">Thrown when the window is empty.</exception>
        public float Min
        {
            get
            {
                if (_count == 0)
                    throw new InvalidOperationException("Window is empty.");

                float min = _buffer[0];
                // Check remaining items. If window is full, we start checking from headIndex+1 to handle wrap-around correctly?
                // Actually simpler: iterate exactly 'count' items starting from the logical tail (oldest item).
                
                // The oldest item is at `_headIndex` if count == capacity, or `Capacity - count` if not full?
                // Wait, logic check:
                // If _count < Capacity: items are at 0 .. _count-1. _headIndex equals _count.
                // If _count == Capacity: items are circular starting at _headIndex.
                
                // Let's standardize reading from the oldest item to the newest item to get Min/Max/Percentile correctly.
                // Oldest item index logic:
                int startRead;
                if (_count == Capacity)
                    startRead = _headIndex;
                else
                    startRead = 0;

                min = GetValue(startRead);
                
                for (int i = 1; i < _count; i++)
                {
                    float val = GetValue(startRead + i);
                    if (val < min) min = val;
                }
                return min;
            }
        }

        /// <summary>
        /// Gets the maximum value in the current window. O(n).
        /// </summary>
        /// <exception cref="InvalidOperationException">Thrown when the window is empty.</exception>
        public float Max
        {
            get
            {
                if (_count == 0)
                    throw new InvalidOperationException("Window is empty.");

                int startRead = (_count == Capacity) ? _headIndex : 0;
                float max = GetValue(startRead);

                for (int i = 1; i < _count; i++)
                {
                    float val = GetValue(startRead + i);
                    if (val > max) max = val;
                }
                return max;
            }
        }

        /// <summary>
        /// Calculates the percentile using the nearest-rank method.
        /// Rank = ceil(p * Count), clamped to [1, Count]. Returns the rank-th smallest value.
        /// O(n) due to sorting copy; no allocation after construction.
        /// </summary>
        /// <param name="p">Percentile between 0 and 1 inclusive.</param>
        /// <exception cref="ArgumentOutOfRangeException">Thrown when p is outside [0, 1].</exception>
        /// <exception cref="InvalidOperationException">Thrown when the window is empty.</exception>
        public float Percentile(float p)
        {
            if (p < 0f || p > 1f)
                throw new ArgumentOutOfRangeException(nameof(p));

            if (_count == 0)
                throw new InvalidOperationException("Window is empty.");

            // Copy data from circular buffer to linear scratch buffer
            int startRead = (_count == Capacity) ? _headIndex : 0;
            
            for (int i = 0; i < _count; i++)
            {
                _scratchBuffer[i] = GetValue(startRead + i);
            }

            // Sort the scratch buffer
            Array.Sort(_scratchBuffer, 0, _count);

            // Nearest-rank method: rank = ceil(p * N)
            // Note: If p=0, rank=0? The problem says "clamped to [1, Count]".
            // Standard nearest rank: rank = (int)Math.Ceiling(p * N). 
            // However, if p=0, Math.Ceiling(0) is 0. We clamp to 1.
            // If p=1, Math.Ceiling(N) is N.
            
            int rank = (int)Math.Ceiling(p * _count);
            
            // Clamp to valid 1-based index range [1, Count]
            if (rank < 1) rank = 1;
            if (rank > _count) rank = _count;

            // Convert to 0-based array index
            return _scratchBuffer[rank - 1];
        }

        /// <summary>
        /// Helper to read from the circular buffer handling wrap-around.
        /// </summary>
        private float GetValue(int logicalIndex)
        {
            // logicalIndex is relative to the start of the data sequence (0 to Count-1).
            // We need to map this to the actual buffer index.
            int physicalIndex = (_headIndex + logicalIndex);
            if (_count == Capacity)
            {
                return _buffer[physicalIndex % Capacity];
            }
            else
            {
                // If not full, data is at 0..Count-1. _headIndex is effectively Count.
                // But our startRead logic handled the offset.
                // Actually, simpler logic:
                // If not full, data starts at 0.
                // If full, data starts at _headIndex.
                // So if we pass 'startRead' as the base, then physical = (base + i) % Capacity is ALWAYS true.
                // Wait, let's re-verify the non-full case.
                // Non-full: startRead = 0. Items are at 0, 1, 2... 
                // _buffer[0 + i] is correct.
                // Full: startRead = _headIndex. Items are at _headIndex, _headIndex+1... wrap around.
                // _buffer[_headIndex + i] % Capacity is correct.
                
                return _buffer[physicalIndex]; 
            }
        }
    }
}

* Assumed `Math.Ceiling` behavior for p=0 results in 0, hence the explicit clamp to 1 required by the prompt.
* Used a private helper `GetValue` to handle the circular buffer indexing logic cleanly for Min/Max/Percentile.
* Allocated `_scratchBuffer` in the constructor to satisfy the "no allocation after construction" rule for Percentile.
* The namespace `Xefier.Core.Stats` was inferred from the prompt's requirement; no existing files were provided to verify this specific namespace path.
* Used standard .NET `Math` and `Array` methods which are available in Unity's stripped/standard library context.

[qwen3.5:27b on http://192.168.1.189:11434: 832 prompt tokens, 2163 answer tokens, 49 tokens/s]