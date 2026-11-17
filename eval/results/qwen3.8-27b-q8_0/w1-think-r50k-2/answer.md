```csharp
#if UNITY_EDITOR
// FILE: ApparelEditorWindow.cs
using System.Collections.Generic;
using UnityEditor;
using UnityEngine;

namespace LiminalLabs.CharacterCustomizer
{
    public class ApparelEditorWindow : EditorWindow
    {
        private enum StatusFilter { All, NotDone, Done, ManuallyHidden }

        private static readonly string[] SlotFilterOptions;

        static ApparelEditorWindow()
        {
            var names = Enum.GetNames(typeof(ApparelSlot));
            SlotFilterOptions = new string[names.Length + 1];
            SlotFilterOptions[0] = "Any slot";
            for (int i = 0; i < names.Length; i++)
                SlotFilterOptions[i + 1] = names[i];
        }

        private List<ApparelObj> allApparel = new List<ApparelObj>();
        private Dictionary<string, ApparelObj> byAssetName = new Dictionary<string, ApparelObj>();
        private List<ApparelObj> shown = new List<ApparelObj>();
        private ApparelObj selected;
        private Vector2 listScroll;
        private Vector2 detailScroll;
        private string search = "";
        private StatusFilter filter = StatusFilter.All;
        private int slotFilterIndex;
        private Editor cachedEditor;
        private bool needsReload;
        private GUIStyle notDoneStyle;
        private GUIStyle hiddenStyle;

        [MenuItem("Tools/Character Customizer/Apparel Editor")]
        public static void Open()
        {
            GetWindow<ApparelEditorWindow>("Apparel Editor");
        }

        private void OnEnable()
        {
            Reload();
        }

        private void OnDisable()
        {
            if (cachedEditor != null)
            {
                DestroyImmediate(cachedEditor);
                cachedEditor = null;
            }
        }

        private void OnProjectChange()
        {
            needsReload = true;
            Repaint();
        }

        private void OnGUI()
        {
            if (needsReload)
            {
                needsReload = false;
                Reload();
            }

            RebuildShown();
            DrawToolbar();

            EditorGUILayout.BeginHorizontal();
            DrawList();
            DrawDetails();
            EditorGUILayout.EndHorizontal();
        }

        // FindAssets is fine: editor tooling, not runtime code.
        private void Reload()
        {
            string prevPath = selected != null ? AssetDatabase.GetAssetPath(selected) : null;

            allApparel.Clear();
            byAssetName.Clear();

            string[] guids = AssetDatabase.FindAssets("t:ApparelObj");
            foreach (string guid in guids)
            {
                string assetPath = AssetDatabase.GUIDToAssetPath(guid);
                var obj = AssetDatabase.LoadAssetAtPath<ApparelObj>(assetPath);
                if (obj == null) continue;
                allApparel.Add(obj);
                byAssetName[obj.name] = obj;
            }

            allApparel.Sort((a, b) => string.CompareOrdinal(a.name, b.name));

            selected = null;
            if (prevPath != null)
            {
                foreach (var a in allApparel)
                {
                    if (AssetDatabase.GetAssetPath(a) == prevPath)
                    {
                        selected = a;
                        break;
                    }
                }
            }

            if (cachedEditor != null)
            {
                DestroyImmediate(cachedEditor);
                cachedEditor = null;
            }
        }

        private void RebuildShown()
        {
            shown.Clear();
            foreach (var apparel in allApparel)
            {
                if (!MatchesSearch(apparel)) continue;
                if (!MatchesStatus(apparel)) continue;
                if (!MatchesSlot(apparel)) continue;
                shown.Add(apparel);
            }
        }

        private bool MatchesSearch(ApparelObj apparel)
        {
            if (string.IsNullOrEmpty(search)) return true;
            if (apparel.name != null && apparel.name.IndexOf(search, System.StringComparison.OrdinalIgnoreCase) >= 0)
                return true;
            if (apparel.Apparel.Name != null && apparel.Apparel.Name.IndexOf(search, System.StringComparison.OrdinalIgnoreCase) >= 0)
                return true;
            if (apparel.Apparel.DisplayName != null && apparel.Apparel.DisplayName.IndexOf(search, System.StringComparison.OrdinalIgnoreCase) >= 0)
                return true;
            return false;
        }

        private bool MatchesStatus(ApparelObj apparel)
        {
            switch (filter)
            {
                case StatusFilter.All: return true;
                case StatusFilter.NotDone: return apparel.NotDone;
                case StatusFilter.Done: return !apparel.NotDone;
                case StatusFilter.ManuallyHidden:
                    return IsManuallyHidden(apparel);
                default: return true;
            }
        }

        private bool MatchesSlot(ApparelObj apparel)
        {
            if (slotFilterIndex <= 0) return true;
            if (apparel.Slots == null) return false;
            var target = (ApparelSlot)(slotFilterIndex - 1);
            foreach (var s in apparel.Slots)
            {
                if (s == target) return true;
            }
            return false;
        }

        private static bool IsManuallyHidden(ApparelObj apparel)
        {
            return !apparel.NotDone &&
                   (!apparel.UsableInCharacterCreator ||
                    (apparel.HiddenOnBodies != null && apparel.HiddenOnBodies.Length > 0));
        }

        private void DrawToolbar()
        {
            EditorGUILayout.BeginHorizontal(EditorStyles.toolbar);

            search = EditorGUILayout.TextField(search, EditorStyles.toolbarSearchField, GUILayout.MinWidth(120));
            filter = (StatusFilter)EditorGUILayout.EnumPopup(filter, EditorStyles.toolbarPopup, GUILayout.Width(110));
            slotFilterIndex = EditorGUILayout.Popup(slotFilterIndex, SlotFilterOptions, EditorStyles.toolbarPopup, GUILayout.Width(90));

            GUILayout.FlexibleSpace();

            GUILayout.Label($"{shown.Count} of {allApparel.Count}", EditorStyles.miniLabel);

            bool anyNotDoneShown = false;
            foreach (var a in shown)
            {
                if (a.NotDone) { anyNotDoneShown = true; break; }
            }

            using (new EditorGUI.DisabledScope(!anyNotDoneShown))
            {
                if (GUILayout.Button("Mark all shown done", EditorStyles.toolbarButton))
                {
                    int count = 0;
                    foreach (var a in shown)
                        if (a.NotDone) count++;

                    if (EditorUtility.DisplayDialog("Mark apparel done",
                            $"Mark {count} apparel done? They become visible to players.",
                            "Mark done", "Cancel"))
                    {
                        var toMark = new List<ApparelObj>();
                        foreach (var a in shown)
                            if (a.NotDone) toMark.Add(a);
                        MarkDone(toMark, byAssetName);
                    }
                }
            }

            if (GUILayout.Button("Refresh", EditorStyles.toolbarButton))
            {
                Reload();
            }

            EditorGUILayout.EndHorizontal();
        }

        private void DrawList()
        {
            EditorGUILayout.BeginVertical(GUILayout.Width(320));
            listScroll = EditorGUILayout.BeginScrollView(listScroll);

            if (shown.Count == 0)
            {
                GUILayout.Label("No apparel matches.");
            }
            else
            {
                HandleArrowKeys();

                foreach (var apparel in shown)
                {
                    Rect row = EditorGUILayout.GetControlRect(false, 20);

                    if (apparel == selected)
                        EditorGUI.DrawRect(row, new Color(0.24f, 0.48f, 0.90f, 0.35f));

                    Rect nameRect = new Rect(row.x, row.y, row.width - 140, row.height);
                    EditorGUI.LabelField(nameRect, apparel.name);

                    string slotText = apparel.Slots != null && apparel.Slots.Length > 0
                        ? apparel.Slots[0].ToString() : "-";
                    Rect slotRect = new Rect(row.x + row.width - 140, row.y, 70, row.height);
                    EditorGUI.Label(slotRect, slotText);

                    Rect statusRect = new Rect(row.x + row.width - 70, row.y, 70, row.height);
                    if (apparel.NotDone)
                    {
                        GUI.Label(statusRect, "Not done", NotDoneStyle);
                    }
                    else if (IsManuallyHidden(apparel))
                    {
                        GUI.Label(statusRect, "Hidden", HiddenStyle);
                    }

                    if (Event.current.type == EventType.MouseDown && row.Contains(Event.current.mousePosition))
                    {
                        selected = apparel;
                        Event.current.Use();
                        GUI.FocusControl(null);
                    }
                }
            }

            EditorGUILayout.EndScrollView();
            EditorGUILayout.EndVertical();
        }

        private void HandleArrowKeys()
        {
            if (Event.current.type != EventType.KeyDown) return;
            if (Event.current.keyCode != KeyCode.UpArrow && Event.current.keyCode != KeyCode.DownArrow) return;
            if (shown.Count == 0) return;

            int idx = shown.IndexOf(selected);

            if (Event.current.keyCode == KeyCode.UpArrow)
            {
                if (idx > 0) selected = shown[idx - 1];
                else if (idx < 0) selected = shown[shown.Count - 1];
            }
            else
            {
                if (idx >= 0 && idx < shown.Count - 1) selected = shown[idx + 1];
                else if (idx < 0) selected = shown[0];
            }

            Event.current.Use();
        }

        private void DrawDetails()
        {
            EditorGUILayout.BeginVertical();

            if (selected == null)
            {
                EditorGUILayout.HelpBox("Select an apparel on the left.", MessageType.Info);
            }
            else
            {
                detailScroll = EditorGUILayout.BeginScrollView(detailScroll);

                using (new EditorGUI.DisabledScope(true))
                {
                    EditorGUILayout.ObjectField("Asset", selected, typeof(ApparelObj), false);
                }

                if (selected.NotDone)
                {
                    EditorGUILayout.HelpBox(
                        "Not done yet: hidden from players on every body and never sold. Mark it done to show it.",
                        MessageType.Warning);
                    if (GUILayout.Button("Mark done", GUILayout.Height(24)))
                    {
                        var single = new List<ApparelObj> { selected };
                        MarkDone(single, byAssetName);
                    }
                }
                else
                {
                    string msg = "Done: visible to players";
                    if (IsManuallyHidden(selected))
                        msg += " (but manually hidden: Usable In Character Creator is off or Hidden On Bodies is set)";
                    EditorGUILayout.HelpBox(msg, MessageType.Info);
                }

                EditorGUILayout.BeginHorizontal();
                if (GUILayout.Button("Ping"))
                {
                    EditorGUIUtility.PingObject(selected);
                }
                if (GUILayout.Button("Select in Project"))
                {
                    Selection.activeObject = selected;
                }
                EditorGUILayout.EndHorizontal();

                Editor.CreateCachedEditor(selected, null, ref cachedEditor);
                cachedEditor.OnInspectorGUI();

                EditorGUILayout.EndScrollView();
            }

            EditorGUILayout.EndVertical();
        }

        private GUIStyle NotDoneStyle => notDoneStyle ?? (notDoneStyle = MakeStatusStyle(new Color(1f, 0.6f, 0.2f)));
        private GUIStyle HiddenStyle => hiddenStyle ?? (hiddenStyle = MakeStatusStyle(new Color(0.5f, 0.5f, 0.5f)));

        private static GUIStyle MakeStatusStyle(Color color)
        {
            var s = new GUIStyle(EditorStyles.miniLabel);
            s.normal.textColor = color;
            return s;
        }

        private static void MarkDone(IEnumerable<ApparelObj> items, Dictionary<string, ApparelObj> byAssetName)
        {
            var toMark = new HashSet<ApparelObj>();
            foreach (var item in items)
            {
                toMark.Add(item);
                var versions = ApparelCatalog.BodyVersionsOf(item.Apparel.Name);
                if (versions != null)
                {
                    foreach (var entry in versions)
                    {
                        if (byAssetName.TryGetValue(entry.AssetName, out var version))
                            toMark.Add(version);
                    }
                }
            }

            var markedNames = new List<string>();
            foreach (var apparel in toMark)
            {
                if (!apparel.NotDone) continue;
                Undo.RecordObject(apparel, "Mark apparel done");
                apparel.NotDone = false;
                EditorUtility.SetDirty(apparel);
                AssetDatabase.SaveAssetIfDirty(apparel);
                markedNames.Add(apparel.name);
            }

            if (markedNames.Count > 0)
                Debug.Log($"[ApparelEditorWindow] Marked done: {string.Join(", ", markedNames)}");
        }
    }
}
#endif
```

- Assumed `CC.scrObj_Apparel.Apparel` has public string fields `Name` and `DisplayName` (the instruction references them; the struct source wasn't provided).
- Assumed `ApparelCatalog.BodyVersionsOf` returns `List<ApparelIndex.Entry>` and `ApparelIndex.Entry` has a public string field `AssetName`, per the description.
- The row layout splits 320 px as 180 (name) + 70 (slot) + 70 (status); if the name overflows it clips since it's a fixed-rect label.
- `Debug.Log` is used in `MarkDone` as explicitly permitted for editor tooling; all other logging is absent since no failure paths were specified.
- After `MarkDone` saves and reimports assets, the in-memory `shown` list still references the same `ApparelObj` instances (their `NotDone` field was mutated in place), so the next `RebuildShown` reflects the change without a full reload.

[qwen3.8:27b-q8_0 on http://192.168.1.232:11434: 3680 prompt tokens, 11509 answer tokens, 52 tokens/s]