using System.Collections;
using System.Collections.Generic;
using UnityEngine;

public class LightService : IEnumerable<ILight>
{
    #region Singleton
    private static LightService instance;
    public static LightService Instance
    {
        get
        {
            if (instance == null)
            {
                instance = new LightService();
            }
            return instance;
        }
    }
    #endregion

    private HashSet<ILight> lights = new HashSet<ILight>();

    /// <summary>
    /// Lights that detectors must see even though they aren't on a physics light layer - carried
    /// lights like the flashlight. Deliberately a small side list: it is iterated per detector tick
    /// and there is roughly one entry per player.
    /// </summary>
    private List<ILight> alwaysDetected = new List<ILight>();

    public int Count => lights.Count;

    /// <summary>
    /// Never feed this to NearbyLightController - it switches lights off, and these are player-owned.
    /// </summary>
    public IReadOnlyList<ILight> AlwaysDetectedLights => alwaysDetected;

    public void AddLight(ILight light)
    {
        if (light == null || !lights.Add(light))
        {
            return;
        }

        if (light.AlwaysDetected)
        {
            alwaysDetected.Add(light);
        }

        LightLevelDetectionService.Instance.OnLightAdded(light);
    }

    public void RemoveLight(ILight light)
    {
        if (light == null || !lights.Remove(light))
        {
            return;
        }

        alwaysDetected.Remove(light);

        LightLevelDetectionService.Instance.OnLightRemoved(light);
    }

    /// <summary>
    /// Re-syncs a registered light after its AlwaysDetected flag changed at runtime.
    /// </summary>
    public void RefreshLight(ILight light)
    {
        if (light == null || !lights.Contains(light))
        {
            return;
        }

        var registered = alwaysDetected.Contains(light);

        if (light.AlwaysDetected && !registered)
        {
            alwaysDetected.Add(light);
        }
        else if (!light.AlwaysDetected && registered)
        {
            alwaysDetected.Remove(light);
        }

        // AlwaysDetected lights are excluded from the range caches, so flipping the flag changes them.
        LightLevelDetectionService.Instance.InvalidateRangeCache();
    }

    public IEnumerator<ILight> GetEnumerator()
    {
        return lights.GetEnumerator();
    }

    IEnumerator IEnumerable.GetEnumerator()
    {
        return GetEnumerator();
    }

    public void SetColorFilter(Color color)
    {
        foreach (var light in lights)
        {
            light.ColorFilter = color;
        }
    }

    public void SetColorFilter(Color color, LayerMask layerMask)
    {
        foreach (var light in lights)
        {
            if (layerMask.IsIncluded(light.gameObject))
            {
                light.ColorFilter = color;
            }
        }
    }
}
