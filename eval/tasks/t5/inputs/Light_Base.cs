using System.Collections;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;
using UnityEngine.Events;
using UnityEngine.Rendering.HighDefinition;
using Xefier.Core.UnityEvents;

// Do NOT put this into a namespace, as it will break Visual Scripting references.
public class Light_Base : MonoBehaviour, ILight
{
    public delegate void SetLightStateEventHandler(ILight.LightState newState, bool ignoreBlinkOn);
    public event SetLightStateEventHandler OnSetLightState;

    [SerializeField] bool setupOnAwake = false;
    [SerializeField] bool setupInEditorNow = false;
    [Header("References")]
    [SerializeField] Light light;
    [SerializeField] HDAdditionalLightData lightData;
    [SerializeField] RenderedLight[] renderedLights;
    [SerializeField] bool flickOn;
    [SerializeField] Light[] extraLights;
    [SerializeField, Tooltip("These lights will not be modified")] 
    LightWrapper[] immutableExtraLights;
    //[SerializeField] LightQualitySettingsObject qualitySettingsObject;
    [SerializeField] HDAdditionalLightData[] extraLightData;
    //[SerializeField] Power_Base powerBase;

    [Header("Settings")]
    //[SerializeField] LightLayerEnum lightLayers;
    [SerializeField] bool setUpLightLayers = true;
    [SerializeField] bool burnedOut = false;
    [SerializeField] float minFlickerTime = 0.03f;
    [SerializeField] float maxFlickerTime = 0.66f;
    [SerializeField] private bool forceFlicker;
    [SerializeField] bool _requiresPower = true;
    [SerializeField] bool canFlicker = true;
    [SerializeField] bool acceptsColorVolumes = true;
    [SerializeField, Tooltip("Detected by light level detectors even when this light isn't on a physics light layer. For carried lights like the flashlight.")]
    bool alwaysDetected = false;
    [SerializeField, Tooltip("Counts as lighting anything within this distance regardless of beam direction. Leave at 0 for normal lights.")]
    float detectionSpillRadius = 0f;
    [Header("Turn On Settings")]
    [SerializeField] bool turnOnBlinking = false;
    [SerializeField] float minTurnOnBlinkTime = 0.2f;
    [SerializeField] float maxTurnOnBlinkTime = 2f;
    [Header("Properties")]
    [SerializeField] List<FlickerVolume> flickerVolumes;
    [SerializeField] List<ColorVolume> colorVolumes;
    [SerializeField] ILight.LightState lightState;
    [SerializeField] float lightDistance = 100;
    [SerializeField] bool contactShadows = true;


    [SerializeField] float baseIntensity;
    [SerializeField] Color baseColor;
    [SerializeField] float baseRange;
    [Header("SECTR")]
    [SerializeField] SECTR_Member member;
    /// <summary>
    /// The SECTR_Member sibling for this light. Used by the portal-aware
    /// membership adapter to assign sector subscriptions after dungeon generation.
    /// Membership of this member is owned exclusively by the adapter; Light_Base
    /// no longer drives member bounds or membership state.
    /// </summary>
    public SECTR_Member Member => member;

    private Color colorFilter = Color.white;
    private Color colorModifier = Color.white;
    private bool wasFlickering;
    private bool hadColorVolume;
    Color[] extraLightBaseColors;
    private ILight.LightState lightStateBeforeFlicker;
    private HashSet<FlickerVolume> flickerVolumesCache;
    private HashSet<ColorVolume> colorVolumesCache;
    private HashSet<Light_Control> lightControls = new HashSet<Light_Control>();

    [Header("Events")]
    [SerializeField] UnityEvent_Bool stateChanged;
    public UnityEvent On;
    public UnityEvent Off;

    public Color _originalColor => baseColor;
    public bool IsLightOn => (lightState == ILight.LightState.On || (IsFlickering && lightStateBeforeFlicker == ILight.LightState.On)) && !burnedOut;
    public bool BurnedOut { get => burnedOut; set { burnedOut = value; UpdateLightState(); } }
    public bool ForceFlicker
    {
        get => forceFlicker; 
        set
        {
            if (canFlicker)
            {
                forceFlicker = value;
                SetLightState(IntendedState, true);
            }
            else
            {
                forceFlicker = false;
            }
        }
    }
    //public float LightDistance { get => lightDistance; set { lightDistance = value; } }
    public bool HasColorVolume => colorVolumesCache.Count > 0; 
    public IEnumerable<RenderedLight> RenderedLights => renderedLights;


    [System.Serializable]
    public class RenderedLight
    {
        public MeshRenderer renderer;
        public int materialIndex;
        [Tooltip("Usually _EmissiveColor")]
        public string materialEmissionPropertyName = "_EmissiveColor";
        //[HideInInspector]
        //Hide inspector once it works
        public Color emissionColor;
    }

    public Light Light => light;

    private LightWrapper[] allLights;

    /// <summary>
    /// Built once and reused. This is enumerated by every LightLevelDetector every tick, so it must
    /// not allocate - it used to build a fresh LightWrapper per sub-light on every call.
    /// </summary>
    public IEnumerable<LightWrapper> Lights => allLights ??= BuildLights();

    private LightWrapper[] BuildLights()
    {
        //TODO: Convert light and extraLights to LightWrapper, BUT need to automatically populate the new field to not lose references!
        var built = new List<LightWrapper>();

        if (light != null)
        {
            built.Add(new LightWrapper(light));
        }

        if (extraLights != null)
        {
            foreach (var extraLight in extraLights)
            {
                if (extraLight != null)
                {
                    built.Add(new LightWrapper(extraLight));
                }
            }
        }

        if (immutableExtraLights != null)
        {
            foreach (var immutableExtraLight in immutableExtraLights)
            {
                if (immutableExtraLight != null && immutableExtraLight.Light != null)
                {
                    built.Add(immutableExtraLight);
                }
            }
        }

        return built.ToArray();
    }
    HDAdditionalLightData ILight._lightData => lightData;
    public ILight.LightState _lightState => lightState;
    //Color ILight._colorMask { get => lightData.color; set => lightData.color = value; }

    /// <summary>
    /// Will be 0 if light is disabled
    /// Returns baseRange if flickering
    /// </summary>
    public float Range => IsFlickering ? baseRange : lightData.range;
    /// <summary>
    /// Won't change when light is disabled
    /// </summary>
    public float BaseRange => baseRange;
    public IEnumerable<Light_Control> LightControls => lightControls;
    public Light_ControlGroup Group { get; set; }
    public bool IsFlickering => forceFlicker || (flickerVolumesCache != null && flickerVolumesCache.Count > 0);

    ILight.OnStateChanged ILight.onStateChanged { get => _onStateChanged; set => _onStateChanged = value; }

    public bool RequiresPower => _requiresPower;
    /// <summary>
    /// See <see cref="ILight.AlwaysDetected"/>. Changing this at runtime re-syncs the LightService
    /// side list, so it is safe to drive from Visual Scripting.
    /// </summary>
    public bool AlwaysDetected
    {
        get => alwaysDetected;
        set
        {
            if (alwaysDetected == value) return;
            alwaysDetected = value;
            LightService.Instance.RefreshLight(this);
        }
    }
    public float DetectionSpillRadius => detectionSpillRadius;
    public bool CanFlicker => canFlicker;
    public bool AcceptsColorVolumes => acceptsColorVolumes;
    public Color ColorFilter
    {
        get => colorFilter;
        set
        {
            colorFilter = value;
            UpdateLightState();
        }
    }
    public Color ColorModifier
    {
        get => colorModifier;
        set
        {
            colorModifier = value;
            ColorFilter = value;
        }
    }
    ILight.OnStateChanged _onStateChanged;

    public void SetIntensityMultiplier(float multipllier)
    {
        light.intensity = baseIntensity * multipllier;
        foreach (Light extraLight in extraLights)
        {
            if (extraLight != null)
            {
                extraLight.intensity = baseIntensity * multipllier;
            }
        }
    }

    public void SetFadeDistance(float distance)
    {
        if (lightData != null)
        {
            lightData.fadeDistance = distance;
            lightData.volumetricFadeDistance = distance;
            lightData.shadowFadeDistance = distance * 2;
        }
        else
        {
            DebugX.LogWarning("Light Data Missing for Game Object: " + gameObject);
        }
        foreach (HDAdditionalLightData lightData in extraLightData)
        {
            lightData.fadeDistance = distance;
            lightData.volumetricFadeDistance = distance;
            lightData.shadowFadeDistance = distance * 2;
        }
    }

    public void SetShadowQuality(int quality)
    {
        if (lightData != null)
        {
            lightData.SetShadowResolution(quality);
            foreach (HDAdditionalLightData lightData in extraLightData)
            {
                lightData.SetShadowResolution(quality);
                lightData.useContactShadow.useOverride = contactShadows;
                lightData.useContactShadow.@override = contactShadows;
                if (contactShadows) { lightData.useContactShadow.level = 1; }
            }
        }
        else
        {
            DebugX.LogWarning("Light Data Missing for Game Object: " + gameObject);
        }
    }
    /*public void SetQualitySettings(int qualitySetting)
    {
        if (qualitySettingsObject!=null && qualitySettingsObject.settings.Length > qualitySetting)
        {
            float fadeDistance = qualitySettingsObject.settings[qualitySetting].FadeDistance;
            lightData.fadeDistance = fadeDistance;
            lightData.volumetricFadeDistance = fadeDistance;
            lightData.shadowFadeDistance= fadeDistance*2;
            foreach (HDAdditionalLightData lightData in extraLightData)
            {
                lightData.fadeDistance = fadeDistance;
                lightData.volumetricFadeDistance = fadeDistance;
                lightData.shadowFadeDistance = fadeDistance*2;
            }
        }
    }*/
    void Awake()
    {
        flickerVolumesCache = new HashSet<FlickerVolume>(flickerVolumes);
        colorVolumesCache = new HashSet<ColorVolume>(colorVolumes);
        if (setUpLightLayers)
        {
            UnityEngine.Rendering.HighDefinition.RenderingLayerMask lightLayerOne = UnityEngine.Rendering.HighDefinition.RenderingLayerMask.LightLayerDefault;
            UnityEngine.Rendering.HighDefinition.RenderingLayerMask lightLayerTwo = UnityEngine.Rendering.HighDefinition.RenderingLayerMask.LightLayer1;
            if (lightData != null)
            {
                lightData.lightlayersMask = lightLayerOne | lightLayerTwo; 
            }
            else
            {
                DebugX.LogError("lightData is null", this);
            }
        }
        if (setupOnAwake)
        {
            SetUpLight();
        }
        if (extraLights!=null && extraLights.Length > 0)
        {
            extraLightBaseColors = new Color[extraLights.Length];
            for (int i = 0; i<extraLights.Length; i++)
            {
                extraLightBaseColors[i] = extraLights[i].color;
            }
        }
    }

    void OnEnable()
    {
        LightService.Instance.AddLight(this);

        _onStateChanged += OnStateChanged;
        colorFilter = colorModifier;
        // Switched off mid-flicker, lightState is whichever blink it stopped on
        SetLightState(IntendedState, true);
        UpdateLightState();
        if (member != null && member.isActiveAndEnabled)
        {
            member.enabled = false;
            member.enabled = true;
        }
    }

    void OnDisable()
    {
        LightService.Instance.RemoveLight(this);
        _onStateChanged -= OnStateChanged;
    }

    void SetUpLight()
    {
       
        if (lightData != null)
        {
            baseIntensity = lightData.intensity;
            baseColor = lightData.color;
            baseRange = lightData.range;
        }
        foreach (RenderedLight rendLight in renderedLights)
        {
            if (rendLight != null)
            {
                rendLight.emissionColor = rendLight.renderer.sharedMaterials[rendLight.materialIndex].GetColor(rendLight.materialEmissionPropertyName);
            }
        }
    }

    void Update()
    {
        if (HasColorVolume)
        {
            foreach (ColorVolume cv in colorVolumesCache.ToArray())
            {
                if (!cv.isActiveAndEnabled || !cv.enabled)
                {
                    RemoveColorVolume(cv);
                }
            }
            UpdateColorState();
        }
    }

    /// <summary>
    /// The state this light is meant to be in. While a flicker or a turn-on blink runs, <see cref="lightState"/> is only
    /// the current blink (FlickerRoutine and TurnOnFlicker switch it on and off); the state last asked for is kept in
    /// lightStateBeforeFlicker, which every SetLightState records. Until the first one, the serialized lightState.
    /// </summary>
    private ILight.LightState IntendedState => hasRequestedState ? lightStateBeforeFlicker : lightState;
    // Not serialized: whether SetLightState has run yet, so lightStateBeforeFlicker holds the state last asked for
    private bool hasRequestedState;

    public void AddFlickerVolume(FlickerVolume volume)
    {
        if (canFlicker)
        {
            // Not lightState: a light that is already flickering (another volume, or the same volume re-adding it) is
            // in a random blink, and recording an "off" blink as its real state turned the light off for good when
            // the flicker ended, here and, on the light's owner, for every peer. The 216 did this to half the lights
            // around it whenever its chase flicker took over from its unseen flicker, and its own light detector then
            // read the room as dark.
            lightStateBeforeFlicker = IntendedState;

            if (!flickerVolumesCache.Contains(volume))
            {
                flickerVolumesCache.Add(volume);
#if UNITY_EDITOR
                flickerVolumes.Add(volume); // Debug
#endif
            }
            UpdateFlickerState();
        }
    }

    public void RemoveFlickerVolume(FlickerVolume volume)
    {
        if (flickerVolumesCache.Contains(volume))
        {
            flickerVolumesCache.Remove(volume);
#if UNITY_EDITOR
            flickerVolumes.Remove(volume); // Debug 
#endif            
        }
        UpdateFlickerState();
    }

    public void RemoveAllFlickerVolumes()
    {
        flickerVolumesCache.Clear();
        UpdateFlickerState();
    }

    public void UpdateFlickerState()
    {
        foreach (FlickerVolume fv in flickerVolumesCache.ToArray())
        {
            if (!fv.isActiveAndEnabled || !fv.enabled)
            {
                RemoveFlickerVolume(fv);
            }
        }
        if (IsFlickering != wasFlickering)
        {
            SetLightState(lightStateBeforeFlicker);
        }
        wasFlickering = IsFlickering;
    }

    public void AddColorVolume(ColorVolume volume)
    {
        if (acceptsColorVolumes)
        {
            if (!colorVolumesCache.Contains(volume))
            {
                colorVolumesCache.Add(volume);
            #if UNITY_EDITOR
                colorVolumes.Add(volume); // Debug
            #endif
            }
            UpdateColorState();
        }
    }

    public void RemoveColorVolume(ColorVolume volume)
    {
        if (colorVolumesCache.Contains(volume))
        {
            colorVolumesCache.Remove(volume);
//#if UNITY_EDITOR
            //colorVolumes.Add(volume); // Debug
//#endif
        }
        UpdateColorState();
    }

    void UpdateColorState()
    {
        //if (hasColorVolume != hadColorVolume)
        //{
            SetColorFromVolumes();
        //}
        hadColorVolume = HasColorVolume;
    }

    void SetColorFromVolumes()
    {
        var first = colorVolumesCache.FirstOrDefault();
        if (first != null)
        {
            ColorVolume volume = first;
            float distance = Vector3.Distance(transform.position, volume.transform.position);
            colorFilter = Color.Lerp(baseColor, volume.Color, volume.Falloff.Evaluate(1-(distance/volume.MaxDistance)));
        }
        else
        {
            colorFilter = colorModifier;
        }
        UpdateLightState();
    }

   
    private void OnStateChanged()
    {
        stateChanged.Invoke(lightState == ILight.LightState.On);
    }

    public void OverrideLightState(bool on)
    {
        if (on)
        {
            SetLightState(ILight.LightState.On);
        }
        else
        {            
            SetLightState(ILight.LightState.Off);
        }
    }

    public void SetLightState(ILight.LightState newState, bool ignoreBlinkOn = false)
    {        
        if (this != null && gameObject != null)
        {
            if (!gameObject.activeInHierarchy)
            {
                ignoreBlinkOn = true;
            }

            // What is asked for is what the light returns to when a flicker ends: a light switched on while it
            // flickers otherwise went back off with the flicker
            lightStateBeforeFlicker = newState;
            hasRequestedState = true;

            if (!IsFlickering || (ignoreBlinkOn || newState == ILight.LightState.Off))
            {
                StopAllCoroutines();
                switch (newState)
                {
                    case ILight.LightState.Off:
                        LightOff(true);
                        break;
                    case ILight.LightState.On:
                        if ((IsFlickering) && lightState != ILight.LightState.On)
                        {
                            float flickTime = Random.Range(minTurnOnBlinkTime, maxTurnOnBlinkTime);
                            StartCoroutine(TurnOnFlicker(flickTime));
                        }
                        else
                        {
                            LightOn(ignoreBlinkOn);
                        }
                        break;
                }
                if (_onStateChanged != null)
                {
                    _onStateChanged.Invoke();
                }
            }
            else
            {
                StartCoroutine(FlickerRoutine());
            }

            var isOn = newState == ILight.LightState.On;
            stateChanged.Invoke(isOn);
            (isOn ? On : Off).Invoke();
            OnSetLightState?.Invoke(newState, ignoreBlinkOn);
        }
        else
        {
            DebugX.LogError("SetLightState Failed: Light destroyed", this);
        }
    }

    void LightOn(bool ignoreBlink = false)
    {
        if (light != null)
        {
            if (lightState==ILight.LightState.Off && turnOnBlinking && !ignoreBlink)
            {
                StartCoroutine(TurnOnFlicker(Random.Range(minTurnOnBlinkTime, maxTurnOnBlinkTime)));
                return;
            }

            var wasOff = lightState != ILight.LightState.On;
            if (wasOff)
            {
                if (_onStateChanged != null)
                {
                    _onStateChanged.Invoke();
                }
            }

            lightState = ILight.LightState.On;
            // Light.enabled belongs to the SECTR culler, which switches off the lights of culled sectors and, applying
            // only visibility changes, switches them back on when the sector is next shown. On/off is carried by range
            // (lightData and extraLightData, here and in LightOff), for the extra lights exactly as for the main light:
            // enabling the extra lights here turned them on behind the culler, lighting through walls, whenever this
            // light came on in a culled sector. Light_Base_SECTR_Member_Bridge pins them into the member's cache so the
            // culler manages them.
            //light.enabled = true;
            lightData.range = baseRange;
            // Xefier.Culling.CullingCoverageToggles.LightOnLeavesExtraLightsToCuller off: enable them here after all, as
            // before 6a3807683b, to bisect a culling regression.
            if (!Xefier.Culling.CullingCoverageToggles.LightOnLeavesExtraLightsToCuller)
            {
                foreach (Light extraLight in extraLights)
                {
                    if (extraLight != null)
                    {
                        extraLight.enabled = true;
                    }
                }
            }
            foreach (HDAdditionalLightData extraLightData in extraLightData)
            {
                if (extraLightData != null)
                {
                    extraLightData.range = baseRange;
                }
            }
            UpdateLightState();
        }
        else
        {
            DebugX.LogError("Light not assigned", this);
        }
    }

    void LightOff(bool stopFlicker = true)
    {
        if (light != null )
        {
            if (stopFlicker)
            {
                lightStateBeforeFlicker = ILight.LightState.Off;
                if (_onStateChanged != null)
                {
                    _onStateChanged.Invoke();
                }
                StopCoroutine(FlickerRoutine());

            }
            if (lightState != ILight.LightState.Off)
            {
                if (_onStateChanged != null)
                {
                    _onStateChanged.Invoke();
                }
            }
            //light.enabled = false;
            lightData.range = 0;
            foreach (HDAdditionalLightData extraLightData in extraLightData)
            {
                if (extraLightData != null)
                {
                    extraLightData.range = 0;
                }
            }
            lightState = ILight.LightState.Off;
            UpdateLightState();
        }
        else
        {
            DebugX.LogError("Light not assigned", this);
        }
    }

    void UpdateLightState()
    {
        if (light != null)
        {
            light.color = baseColor * colorFilter;
            if (extraLightBaseColors != null && extraLightBaseColors.Length > 0)
            {
                for (int i = 0; i < extraLightBaseColors.Length; i++)
                {
                    if (extraLights[i] != null && extraLightBaseColors[i] != null)
                    {
                        extraLights[i].color = extraLightBaseColors[i] * colorFilter;
                    }
                }
            }
            /*foreach (Light extraLight in extraLights)
            {
                if (extraLight != null)
                {
                    extraLight.color = baseColor * colorFilter;
                }
            }*/
            foreach (RenderedLight rendLight in renderedLights)
            {
                if (rendLight != null)
                {
                    if (rendLight.renderer != null)
                    {
                        Material mat = rendLight.renderer.materials[rendLight.materialIndex];
                        if (mat != null)
                        {
                            mat.SetColor(rendLight.materialEmissionPropertyName, rendLight.emissionColor * (lightState == ILight.LightState.On && !burnedOut ? 1 : 0) * colorFilter);
                            //Is this same in HDRP?
                            mat.EnableKeyword("_EMISSION");
                        }
                        else
                        {
                            DebugX.LogError("RenderedLight Material is null", this);
                        }
                    }
                    else
                    {
                        DebugX.LogError("RenderedLight.renderer is null", this);
                    }
                }
                else
                {
                    DebugX.LogError("RenderedLight is null", this);
                }
            }
            //DebugX.Log("UPDATING LIGHT STATE: " + (lightState == ILight.LightState.On).ToString()); 
            stateChanged.Invoke(lightState == ILight.LightState.On); 
        }
    }
    IEnumerator TurnOnFlicker(float time)
    {
        flickOn = false;
        if (minFlickerTime > maxFlickerTime)
        {
            minFlickerTime = maxFlickerTime;
        }

        if (maxFlickerTime > 0)
        {
            while (time > 0)
            {
                time -= Time.deltaTime;
                if (flickOn)
                {
                    LightOn(true);
                }
                else
                {
                    LightOff(false);
                }

                var rand = Random.Range(minFlickerTime, maxFlickerTime);
                yield return new WaitForSeconds(Mathf.Min(time, rand));
                time -= rand;
                flickOn = !flickOn;
            }
        }
        LightOn(true);
    }

    IEnumerator FlickerRoutine()
    {
        flickOn = true;
        while (IsFlickering)
        {
            if (flickOn)
            {
                LightOn(true);
            }
            else
            {
                LightOff(false);
            }
            float rand = Random.Range(minFlickerTime, maxFlickerTime);
            while (rand > 0)
            {
                rand -= Time.deltaTime;
                yield return null;
            }
            flickOn = !flickOn;
        }
    }

    public void AddLightControl(Light_Control lightControl)
    {
        lightControls.Add(lightControl);
    }

    void OnValidate()
    {
        if (setupInEditorNow)
        {
            setupInEditorNow = false;
            SetUpLight();
        }

        if (immutableExtraLights != null)
        {
            foreach (var light in immutableExtraLights)
            {
                light.OnValidate();
            }
        }
    }
    
}