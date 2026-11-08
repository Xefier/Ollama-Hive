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
        foreach (var l in SceneLights())
        {
            try { l.ColorFilter = target; }
            catch (System.Exception e) { DebugX.Log(e); }
        }
    }

    public void LightsRandomColoursModifer(bool b)
    {
        if (!b) return;

        foreach (var l in SceneLights())
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

        foreach (var l in SceneLights())
        {
            l.ColorFilter = discoColours[Mathf.RoundToInt(Random.Range(0, discoColours.Count - 1))];
        }
    }

    public void LightsOff(bool b)
    {
        if (!b) return;

        foreach (var l in SceneLights())
        {
            l.SetLightState(ILight.LightState.Off);
        }
    }

    /// <summary>
    /// The Light_Base components LightService holds (each one registers in OnEnable). A copy is returned because
    /// setting a light can switch others on or off through their events, and that changes the registry mid-loop.
    /// Called from one-shot modifiers, never per frame, so the list allocation is fine here.
    /// </summary>
    private List<Light_Base> SceneLights()
    {
        var lights = new List<Light_Base>(LightService.Instance.Count);
        foreach (var light in LightService.Instance)
        {
            if (light is Light_Base lightBase)
            {
                lights.Add(lightBase);
            }
        }
        return lights;
    }
}
```

- Lights now come from the existing `LightService.Instance` registry (filled in `Light_Base.OnEnable`/`OnDisable`), so no scene scan and no change to `Light_Base.cs` or `LightService.cs`. The four loops share one helper, `SceneLights()`.
- Behaviour difference, not verified: a `Light_Base` whose component is disabled while its GameObject stays active was reached by `FindObjectsOfType` before, but is not in the registry now, so it no longer changes colour or turns off. If that case matters, a registry filled in `Light_Base.Awake`/`OnDestroy` with an `activeInHierarchy` check would match the old behaviour exactly; that needs edits to `Light_Base.cs`.
- Assumed every `ILight` in `LightService` that is a `Light_Base` is the only kind the old code touched; other `ILight` implementations are skipped, as before.
- Kept the original lookup (`ContainsKey(colourName)` but `availableColours[colourName.ToLower()]`) and the disco index expression unchanged; they are not part of this task, but the lookup would throw for mixed-case names.
- Not compiled or run.
