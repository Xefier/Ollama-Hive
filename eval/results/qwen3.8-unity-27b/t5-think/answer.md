```csharp
// FILE: NonLinearModifierManager.cs
using System;
using System.Collections.Generic;
using UnityEngine;
using Fusion;
using Xefier.Core.Linq;
using FIMSpace.Generating;
using Unity.VisualScripting;

/// <summary>
/// Handles non-linear scene modifiers (hazard triggering, light changes).
/// Hazard instantiation is fully delegated to HazardSpawnManager.
/// </summary>
public class NonLinearModifierManager : Singleton<NonLinearModifierManager>
{
    // Scene Var names can be found in the Non Linear Prefab:
    // Non Linear > Modifier Manager > Modifier_SpawnSomething / LightColours

    public SerializableDictionary<string, Color> availableColours = new();
    public List<Color> discoColours = new();

    // ── Hazard spawning (forwarded to HazardSpawnManager) ────────────────────

    public void SpawnBalloons(bool b) => HazardSpawnManager.Instance.SpawnBalloons(b);
    public void SpawnBrokenGlass(bool b) => HazardSpawnManager.Instance.SpawnBrokenGlass(b);
    public void SpawnNecroEggs(bool b) => HazardSpawnManager.Instance.SpawnNecroEggs(b);
    public void SpawnStinkBalloons(bool b) => HazardSpawnManager.Instance.SpawnStinkBalloons(b);
    public void SpawnLeeches(bool b) => HazardSpawnManager.Instance.SpawnLeeches(b);
    public void SpawnWhoopeeCushion(bool b) => HazardSpawnManager.Instance.SpawnWhoopeeCushion(b);

    // ── Light modifiers ───────────────────────────────────────────────────────

    public void LightsRed(bool b) { if (b) LightsOneColourModifier("red"); }
    public void LightsOrange(bool b) { if (b) LightsOneColourModifier("orange"); }
    public void LightsYellow(bool b) { if (b) LightsOneColourModifier("yellow"); }
    public void LightsGreen(bool b) { if (b) LightsOneColourModifier("green"); }
    public void LightsBlue(bool b) { if (b) LightsOneColourModifier("blue"); }
    public void LightsIndigo(bool b) { if (b) LightsOneColourModifier("indigo"); }
    public void LightsViolet(bool b) { if (b) LightsOneColourModifier("violet"); }
    public void LightsCyan(bool b) { if (b) LightsOneColourModifier("cyan"); }
    public void LightsMagenta(bool b) { if (b) LightsOneColourModifier("magenta"); }
    public void LightsNormal(bool b) { /* intentional no-op */ }

    public void LightsOneColourModifier(string colourName)
    {
        if (!availableColours.ContainsKey(colourName))
        {
            DebugX.LogError($"<b>{colourName}</b> was not found in availableColours");
            return;
        }

        Color target = availableColours[colourName.ToLower()];
        ForEachLight(l =>
        {
            try { l.ColorFilter = target; }
            catch (System.Exception e) { DebugX.Log(e); }
        });
    }

    public void LightsRandomColoursModifer(bool b)
    {
        if (!b) return;

        ForEachLight(l =>
        {
            try
            {
                l.ColorFilter = new Color(
                    Random.Range(0f, 1f),
                    Random.Range(0f, 1f),
                    Random.Range(0f, 1f));
            }
            catch (System.Exception e) { DebugX.Log(e); }
        });
    }

    public void LightsDisco(bool b)
    {
        if (!b) return;

        ForEachLight(l =>
        {
            l.ColorFilter = discoColours[Mathf.RoundToInt(Random.Range(0, discoColours.Count - 1))];
        });
    }

    public void LightsOff(bool b)
    {
        if (!b) return;

        ForEachLight(l =>
        {
            l.SetLightState(ILight.LightState.Off);
        });
    }

    /// <summary>
    /// Runs <paramref name="action"/> on every light registered with <see cref="LightService"/>. LightService keeps its own
    /// registry (Light_Base adds and removes itself on enable/disable), which replaces the old FindObjectsOfType scene
    /// scan, forbidden in runtime code.
    /// </summary>
    private static void ForEachLight(Action<ILight> action)
    {
        foreach (var light in LightService.Instance)
        {
            action(light);
        }
    }
}
```

- Only NonLinearModifierManager.cs changed; Light_Base.cs and LightService.cs already provide the registry needed.
- Assumed `ILight` declares `SetLightState` and `ColorFilter` (Light_Base implements both publicly, and LightService.SetColorFilter already assigns `ColorFilter` through `ILight`); SetLightState on the interface was not directly visible in the given files.
- The registry holds lights whose `OnEnable` has run (active lights), matching what `FindObjectsOfType<Light_Base>()` returned.
- Kept the try/catch around `ColorFilter` in the two places it existed, and its absence in LightsDisco, as before.

[qwen3.8-unity:27b on http://192.168.1.182:11434: 8382 prompt tokens, 2435 answer tokens, 25 tokens/s]