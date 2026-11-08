```csharp
// FILE: NonLinearModifierManager.cs
using System.Collections.Generic;
using UnityEngine;
using Xefier.Core.Linq;
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
        
        // Avoid FindObjectsOfType; use the existing registry to iterate lights efficiently.
        foreach (var light in LightService.Instance)
        {
            try 
            {
                if (light is Light_Base baseLight)
                {
                    baseLight.ColorFilter = target;
                }
            }
            catch (System.Exception e) 
            { 
                DebugX.Log(e); 
            }
        }
    }

    public void LightsRandomColoursModifer(bool b)
    {
        if (!b) return;

        foreach (var light in LightService.Instance)
        {
            try
            {
                if (light is Light_Base baseLight)
                {
                    baseLight.ColorFilter = new Color(
                        Random.Range(0f, 1f),
                        Random.Range(0f, 1f),
                        Random.Range(0f, 1f));
                }
            }
            catch (System.Exception e) 
            { 
                DebugX.Log(e); 
            }
        }
    }

    public void LightsDisco(bool b)
    {
        if (!b) return;

        foreach (var light in LightService.Instance)
        {
            if (light is Light_Base baseLight)
            {
                baseLight.ColorFilter = discoColours[Mathf.RoundToInt(Random.Range(0, discoColours.Count - 1))];
            }
        }
    }

    public void LightsOff(bool b)
    {
        if (!b) return;

        foreach (var light in LightService.Instance)
        {
            if (light is Light_Base baseLight)
            {
                baseLight.SetLightState(ILight.LightState.Off);
            }
        }
    }
}
```

*   Replaced all `FindObjectsOfType<Light_Base>()` calls with iteration over `LightService.Instance`, which acts as the central registry for lights in this project.
*   Casts `ILight` to `Light_Base` within the loop to access specific implementation details while avoiding scene scans.
*   Removed unused Fusion and Xefier.Linq imports from `NonLinearModifierManager.cs`.
*   Ensured no new serialized fields were added and logging continues to use `DebugX`.

[qwen3.5:27b on http://192.168.1.189:11434: 8424 prompt tokens, 1131 answer tokens, 47 tokens/s]