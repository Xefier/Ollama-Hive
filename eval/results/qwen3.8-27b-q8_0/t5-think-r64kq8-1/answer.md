```csharp
// FILE: NonLinearModifierManager.cs
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
        foreach (var l in LightService.Instance)
        {
            try { l.ColorFilter = target; }
            catch (System.Exception e) { DebugX.Log(e); }
        }
    }

    public void LightsRandomColoursModifer(bool b)
    {
        if (!b) return;

        foreach (var l in LightService.Instance)
        {
            try
            {
                l.ColorFilter = new Color(
                    Random.Range(0f, 1f),
                    Random.Range(0f, 1f),
                    Random.Range(0f, 1f));
            }
            catch (System.Exception e) { DebugX.Log(e); }
        }
    }

    public void LightsDisco(bool b)
    {
        if (!b) return;

        foreach (var l in LightService.Instance)
        {
            l.ColorFilter = discoColours[Mathf.RoundToInt(Random.Range(0, discoColours.Count - 1))];
        }
    }

    public void LightsOff(bool b)
    {
        if (!b) return;

        foreach (var l in LightService.Instance)
        {
            l.SetLightState(ILight.LightState.Off);
        }
    }
}
```

- `SetLightState(ILight.LightState)` is called on `ILight` (the element type of `LightService`). I didn't see the `ILight` interface source in the given files, but `LightService.SetColorFilter` already calls `light.ColorFilter = color` on `ILight`, and the parameter type `ILight.LightState` strongly implies the method is on the interface. If it isn't, a cast to `Light_Base` would be needed.
- `Light_Base` registers itself via `LightService.Instance.AddLight(this)` in `OnEnable`, so every active light in the scene is already in the registry—no scene scan needed.
- Behaviour is preserved: same lights are touched, same try/catch guards, same random/disco/off logic.

[qwen3.8:27b-q8_0 on http://192.168.1.232:11434: 8382 prompt tokens, 3103 answer tokens, 51 tokens/s]