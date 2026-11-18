```csharp
// FILE: NonLinearModifierManager.cs
﻿using System.Collections.Generic;
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

    /// <summary>
    /// Applies to every active Light_Base through the LightService registry (Light_Base registers in
    /// OnEnable and unregisters in OnDisable), so this never scans the scene. A light that throws is
    /// logged and the rest still get the change, as before.
    /// </summary>
    private static void ForEachLight(System.Action<Light_Base> action)
    {
        foreach (var l in LightService.Instance)
        {
            if (l is Light_Base light)
            {
                try { action(light); }
                catch (System.Exception e) { DebugX.Log(e); }
            }
        }
    }

    public void LightsOneColourModifier(string colourName)
    {
        if (!availableColours.ContainsKey(colourName))
        {
            DebugX.LogError($"<b>{colourName}</b> was not found in availableColours");
            return;
        }

        Color target = availableColours[colourName.ToLower()];
        ForEachLight(l => { l.ColorFilter = target; });
    }

    public void LightsRandomColoursModifer(bool b)
    {
        if (!b) return;

        ForEachLight(l =>
        {
            l.ColorFilter = new Color(
                Random.Range(0f, 1f),
                Random.Range(0f, 1f),
                Random.Range(0f, 1f));
        });
    }

    public void LightsDisco(bool b)
    {
        if (!b) return;

        ForEachLight(l => { l.ColorFilter = discoColours[Mathf.RoundToInt(Random.Range(0, discoColours.Count - 1))]; });
    }

    public void LightsOff(bool b)
    {
        if (!b) return;

        ForEachLight(l => { l.SetLightState(ILight.LightState.Off); });
    }
}
```

- The scene scan is gone: every modifier now iterates `LightService.Instance`, whose registry Light_Base maintains in OnEnable/OnDisable. It holds the same set FindObjectsOfType returned (enabled lights only), plus a `is Light_Base` filter in case another ILight implementation ever registers.
- The per-light try/catch that two modifiers had and the other two didn't is now in the shared helper for all four; nothing changes about what the lights receive, exceptions are only logged either way.
- I did not modify Light_Base.cs or LightService.cs; neither needed changes.

[qwen3.8-unity:27b on http://192.168.1.189:11434: 8382 prompt tokens, 2845 answer tokens, 62 tokens/s]