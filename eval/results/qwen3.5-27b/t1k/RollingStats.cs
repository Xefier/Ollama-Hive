// FILE: RollingStats.cs
namespace Xefier.Core.Stats;

using System;

/// <summary>
/// Tracks statistics over a sliding window of floating-point samples without allocation in runtime operations.
/// </summary>
public sealed class RollingStats
{
    private readonly float[] _samples;
    private readonly int _capacity;
    private int _head; // Index of the oldest sample in the window
    private int _count; // Number of samples currently in the window (0..Capacity)
    private double _sum; // Running sum as double to minimize precision loss

    /// <summary>
    /// Preallocated scratch buffer used for sorting during Percentile calculation.
    /// </summary>
    private readonly float[] _scratchBuffer;

    /// <summary>
    /// Creates a new RollingStats instance with the specified window size.
    /// </summary>
    /// <param name="capacity">The maximum number of samples to retain. Must be >= 1.</param>
    /// <exception cref="ArgumentOutOfRangeException">Thrown if capacity is less than 1.</exception>
    public RollingStats(int capacity)
    {
        if (capacity < 1)
            throw new ArgumentOutOfRangeException(nameof(capacity), "Capacity must be at least 1.");

        _capacity = capacity;
        _samples = new float[capacity];
        _scratchBuffer = new float[capacity];
        _head = 0;
        _count = 0;
        _sum = 0.0;
    }

    /// <summary>
    /// The current number of samples in the window.
    /// </summary>
    public int Count => _count;

    /// <summary>
    /// The maximum capacity of the window.
    /// </summary>
    public int Capacity => _capacity;

    /// <summary>
    /// Adds a new sample to the window. If the window is full, the oldest sample is evicted.
    /// </summary>
    /// <param name="value">The sample value.</param>
    /// <remarks>O(1), no allocation.</remarks>
    public void Add(float value)
    {
        // Calculate index for the new write position based on current window state
        int writeIndex = (_head + _count) % _capacity;

        if (_count == _capacity)
        {
            // Window is full: evict oldest sample before overwriting
            float oldSample = _samples[writeIndex];
            _sum -= oldSample;
            
            // Update head to point to the next oldest sample (effectively discarding current writeIndex)
            _head = (_head + 1) % _capacity;
        }
        else
        {
            // Window not full: simply increment count, head stays same until full
            _count++;
        }

        _samples[writeIndex] = value;
        _sum += value;
    }

    /// <summary>
    /// Calculates the arithmetic mean of the current window.
    /// </summary>
    /// <exception cref="InvalidOperationException">Thrown when Count is 0.</exception>
    public float Mean
    {
        get
        {
            if (_count == 0) throw new InvalidOperationException("Cannot calculate Mean on empty window.");
            return (float)(_sum / _count);
        }
    }

    /// <summary>
    /// Finds the minimum value in the current window.
    /// </summary>
    /// <exception cref="InvalidOperationException">Thrown when Count is 0.</exception>
    public float Min
    {
        get
        {
            if (_count == 0) throw new InvalidOperationException("Cannot calculate Min on empty window.");

            float min = _samples[_head];
            for (int i = 1; i < _count; i++)
            {
                int idx = (_head + i) % _capacity;
                if (_samples[idx] < min)
                {
                    min = _samples[idx];
                }
            }
            return min;
        }
    }

    /// <summary>
    /// Finds the maximum value in the current window.
    /// </summary>
    /// <exception cref="InvalidOperationException">Thrown when Count is 0.</exception>
    public float Max
    {
        get
        {
            if (_count == 0) throw new InvalidOperationException("Cannot calculate Max on empty window.");

            float max = _samples[_head];
            for (int i = 1; i < _count; i++)
            {
                int idx = (_head + i) % _capacity;
                if (_samples[idx] > max)
                {
                    max = _samples[idx];
                }
            }
            return max;
        }
    }

    /// <summary>
    /// Calculates the percentile using the nearest-rank method.
    /// </summary>
    /// <param name="p">The percentile value between 0 and 1 inclusive.</param>
    /// <returns>The value at the calculated rank.</returns>
    /// <exception cref="ArgumentOutOfRangeException">Thrown if p is outside [0, 1] or Count is 0.</exception>
    public float Percentile(float p)
    {
        if (p < 0f || p > 1f)
            throw new ArgumentOutOfRangeException(nameof(p), "Percentile must be between 0 and 1.");

        if (_count == 0) throw new InvalidOperationException("Cannot calculate Percentile on empty window.");

        // Copy current window to scratch buffer for sorting (preallocated)
        int i = 0;
        while (i < _count)
        {
            _scratchBuffer[i] = _samples[(_head + i) % _capacity];
            i++;
        }

        // Sort the scratch array
        Array.Sort(_scratchBuffer, 0, _count);

        // Nearest-rank method: rank = ceil(p * Count)
        int rank = (int)Math.Ceiling(p * _count);

        // Clamp rank to [1, Count]
        if (rank < 1) rank = 1;
        if (rank > _count) rank = _count;

        // Convert 1-based rank to 0-based index
        return _scratchBuffer[rank - 1];
    }

    /// <summary>
    /// Clears all samples from the window.
    /// </summary>
    public void Clear()
    {
        _count = 0;
        _head = 0;
        _sum = 0.0;
        // No need to clear array contents as they will be overwritten on Add
    }
}
