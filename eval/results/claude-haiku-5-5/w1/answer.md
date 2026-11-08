```csharp
// FILE: ApparelEditorWindow.cs
#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using System.Linq;
using UnityEditor;
using UnityEngine;

namespace LiminalLabs.CharacterCustomizer
{
    // Editor tooling: FindAssets and LoadAssetAtPath scan the project here, never at runtime.
    public class ApparelEditorWindow : EditorWindow
    {
        private enum StatusFilter { All, NotDone, Done, ManuallyHidden }

        private static readonly Color SelectionColor = new Color(0.24f, 0.48f, 0.90f, 0.35f);

        private const float ListWidth = 320f;
        private const float RowHeight = 20f;
        private const float SlotColumnWidth = 70f;
        private const float StatusColumnWidth = 70f;

        private readonly List<ApparelObj> all = new List<ApparelObj>();
        private readonly List<ApparelObj> shown = new List<ApparelObj>();
        private readonly Dictionary<string, ApparelObj> byAssetName = new Dictionary<string, ApparelObj>();

        private ApparelSlot[] slotValues;
        private string[] slotOptions;
        private string search = "";
        private StatusFilter filter;
        private int slotIndex;
        private Vector2 listScroll;
        private Vector2 detailScroll;
        private ApparelObj selected;
        private bool reloadPending;
        private Editor cachedEditor;

        private GUIStyle notDoneStyle;
        private GUIStyle hiddenStyle;

        [MenuItem("Tools/Character Customizer/Apparel Editor")]
        static void Open()
        {
            GetWindow<ApparelEditorWindow>("Apparel Editor");
        }

        void OnEnable()
        {
            slotValues = (ApparelSlot[])Enum.GetValues(typeof(ApparelSlot));
            slotOptions = new[] { "Any slot" }.Concat(Enum.GetNames(typeof(ApparelSlot))).ToArray();
            Reload();
        }

        void OnDisable()
        {
            if (cachedEditor != null) DestroyImmediate(cachedEditor);
            cachedEditor = null;
        }

        void OnProjectChange()
        {
            reloadPending = true;
            Repaint();
        }

        void OnGUI()
        {
            if (reloadPending && Event.current.type == EventType.Layout) Reload();
            EnsureStyles();
            RebuildShown();

            DrawToolbar();
            EditorGUILayout.BeginHorizontal();
            DrawList();
            DrawDetails();
            EditorGUILayout.EndHorizontal();
            HandleArrowKeys();
        }

        void Reload()
        {
            string selectedPath = selected != null ? AssetDatabase.GetAssetPath(selected) : null;

            all.Clear();
            byAssetName.Clear();
            // Editor tooling: scanning the project for assets is fine in this window.
            foreach (string guid in AssetDatabase.FindAssets("t:ApparelObj"))
            {
                var apparel = AssetDatabase.LoadAssetAtPath<ApparelObj>(AssetDatabase.GUIDToAssetPath(guid));
                if (apparel == null) continue;
                all.Add(apparel);
                byAssetName[apparel.name] = apparel;
            }
            all.Sort((a, b) => string.CompareOrdinal(a.name, b.name));

            selected = selectedPath != null ? all.FirstOrDefault(a => AssetDatabase.GetAssetPath(a) == selectedPath) : null;
            reloadPending = false;
            RebuildShown();
            Repaint();
        }

        void EnsureStyles()
        {
            if (notDoneStyle != null) return;
            notDoneStyle = new GUIStyle(EditorStyles.miniLabel);
            notDoneStyle.normal.textColor = new Color(1f, 0.6f, 0.2f);
            hiddenStyle = new GUIStyle(EditorStyles.miniLabel);
            hiddenStyle.normal.textColor = Color.gray;
        }

        void RebuildShown()
        {
            shown.Clear();
            for (int i = 0; i < all.Count; i++)
            {
                if (Matches(all[i])) shown.Add(all[i]);
            }
        }

        bool Matches(ApparelObj apparel)
        {
            if (!string.IsNullOrEmpty(search)
                && !TextContains(apparel.name, search)
                && !TextContains(apparel.Apparel.Name, search)
                && !TextContains(apparel.Apparel.DisplayName, search)) return false;

            switch (filter)
            {
                case StatusFilter.NotDone: if (!apparel.NotDone) return false; break;
                case StatusFilter.Done: if (apparel.NotDone) return false; break;
                case StatusFilter.ManuallyHidden: if (apparel.NotDone || !IsManuallyHidden(apparel)) return false; break;
            }

            if (slotIndex > 0 && (apparel.Slots == null || Array.IndexOf(apparel.Slots, slotValues[slotIndex - 1]) < 0)) return false;
            return true;
        }

        static bool TextContains(string text, string search)
        {
            return text != null && text.IndexOf(search, StringComparison.OrdinalIgnoreCase) >= 0;
        }

        static bool IsManuallyHidden(ApparelObj apparel)
        {
            return !apparel.UsableInCharacterCreator || (apparel.HiddenOnBodies != null && apparel.HiddenOnBodies.Length > 0);
        }

        static int CountNotDone(List<ApparelObj> items)
        {
            int count = 0;
            for (int i = 0; i < items.Count; i++)
            {
                if (items[i].NotDone) count++;
            }
            return count;
        }

        void DrawToolbar()
        {
            EditorGUILayout.BeginHorizontal(EditorStyles.toolbar);
            search = EditorGUILayout.TextField(search, EditorStyles.toolbarSearchField, GUILayout.MinWidth(120));
            filter = (StatusFilter)EditorGUILayout.EnumPopup(filter, EditorStyles.toolbarPopup, GUILayout.Width(110));
            slotIndex = EditorGUILayout.Popup(slotIndex, slotOptions, EditorStyles.toolbarPopup, GUILayout.Width(90));
            GUILayout.FlexibleSpace();
            GUILayout.Label($"{shown.Count} of {all.Count}", EditorStyles.miniLabel);

            int notDoneShown = CountNotDone(shown);
            using (new EditorGUI.DisabledScope(notDoneShown == 0))
            {
                if (GUILayout.Button("Mark all shown done", EditorStyles.toolbarButton)
                    && EditorUtility.DisplayDialog("Mark apparel done",
                        $"Mark {notDoneShown} apparel done? They become visible to players.", "Mark done", "Cancel"))
                {
                    MarkDone(shown, byAssetName);
                }
            }
            if (GUILayout.Button("Refresh", EditorStyles.toolbarButton)) Reload();
            EditorGUILayout.EndHorizontal();
        }

        void DrawList()
        {
            EditorGUILayout.BeginVertical(GUILayout.Width(ListWidth));
            listScroll = EditorGUILayout.BeginScrollView(listScroll);
            if (shown.Count == 0) GUILayout.Label("No apparel matches.");
            for (int i = 0; i < shown.Count; i++) DrawRow(shown[i]);
            EditorGUILayout.EndScrollView();
            EditorGUILayout.EndVertical();
        }

        void DrawRow(ApparelObj apparel)
        {
            Rect row = EditorGUILayout.GetControlRect(false, RowHeight);
            if (apparel == selected) EditorGUI.DrawRect(row, SelectionColor);

            Rect nameRect = new Rect(row.x, row.y, row.width - SlotColumnWidth - StatusColumnWidth, row.height);
            Rect slotRect = new Rect(nameRect.xMax, row.y, SlotColumnWidth, row.height);
            Rect statusRect = new Rect(slotRect.xMax, row.y, StatusColumnWidth, row.height);
            EditorGUI.LabelField(nameRect, apparel.name);
            EditorGUI.LabelField(slotRect, apparel.Slots != null && apparel.Slots.Length > 0 ? apparel.Slots[0].ToString() : "-");
            if (apparel.NotDone) EditorGUI.LabelField(statusRect, "Not done", notDoneStyle);
            else if (IsManuallyHidden(apparel)) EditorGUI.LabelField(statusRect, "Hidden", hiddenStyle);

            if (Event.current.type == EventType.MouseDown && row.Contains(Event.current.mousePosition))
            {
                selected = apparel;
                Event.current.Use();
                GUI.FocusControl(null);
                Repaint();
            }
        }

        void HandleArrowKeys()
        {
            if (Event.current.type != EventType.KeyDown || shown.Count == 0) return;

            int step = Event.current.keyCode == KeyCode.UpArrow ? -1 : Event.current.keyCode == KeyCode.DownArrow ? 1 : 0;
            if (step == 0) return;

            int index = shown.IndexOf(selected);
            if (index < 0) index = step > 0 ? 0 : shown.Count - 1;
            else index = Mathf.Clamp(index + step, 0, shown.Count - 1);

            selected = shown[index];
            Event.current.Use();
            Repaint();
        }

        void DrawDetails()
        {
            EditorGUILayout.BeginVertical();
            detailScroll = EditorGUILayout.BeginScrollView(detailScroll);
            if (selected == null) EditorGUILayout.HelpBox("Select an apparel on the left.", MessageType.Info);
            else DrawSelected();
            EditorGUILayout.EndScrollView();
            EditorGUILayout.EndVertical();
        }

        void DrawSelected()
        {
            using (new EditorGUI.DisabledScope(true))
            {
                EditorGUILayout.ObjectField("Asset", selected, typeof(ApparelObj), false);
            }

            if (selected.NotDone)
            {
                EditorGUILayout.HelpBox("Not done yet: hidden from players on every body and never sold. Mark it done to show it.", MessageType.Warning);
                if (GUILayout.Button("Mark done", GUILayout.Height(24))) MarkDone(new[] { selected }, byAssetName);
            }
            else
            {
                string done = IsManuallyHidden(selected)
                    ? "Done: visible to players (but manually hidden: Usable In Character Creator is off or Hidden On Bodies is set)"
                    : "Done: visible to players";
                EditorGUILayout.HelpBox(done, MessageType.Info);
            }

            EditorGUILayout.BeginHorizontal();
            if (GUILayout.Button("Ping")) EditorGUIUtility.PingObject(selected);
            if (GUILayout.Button("Select in Project")) Selection.activeObject = selected;
            EditorGUILayout.EndHorizontal();

            Editor.CreateCachedEditor(selected, null, ref cachedEditor);
            cachedEditor.OnInspectorGUI();
        }

        // One place for marking done, used by the list's button and the details button. A garment's
        // body versions share one status, so every version is marked with the item.
        static void MarkDone(IEnumerable<ApparelObj> items, Dictionary<string, ApparelObj> byAssetName)
        {
            var toMark = new HashSet<ApparelObj>();
            foreach (ApparelObj item in items)
            {
                toMark.Add(item);
                foreach (ApparelIndex.Entry version in ApparelCatalog.BodyVersionsOf(item.Apparel.Name))
                {
                    if (byAssetName.TryGetValue(version.AssetName, out ApparelObj other)) toMark.Add(other);
                }
            }

            var names = new List<string>();
            foreach (ApparelObj apparel in toMark)
            {
                if (!apparel.NotDone) continue;
                Undo.RecordObject(apparel, "Mark apparel done");
                apparel.NotDone = false;
                EditorUtility.SetDirty(apparel);
                // Save each asset alone: the editor is shared, so no AssetDatabase.SaveAssets().
                AssetDatabase.SaveAssetIfDirty(apparel);
                names.Add(apparel.name);
            }

            if (names.Count > 0) DebugX.Log($"[ApparelEditorWindow] Marked done: {string.Join(", ", names)}");
        }
    }
}
#endif
```

- `ApparelCatalog`, `ApparelIndex.Entry` and `DebugX` are not in the given files; I assumed they sit in `LiminalLabs.CharacterCustomizer` (or the global namespace for `DebugX`) and that `DebugX.Log` takes a single string.
- The prompt asks for `Debug.Log` in the summary line, but rules.txt forbids `Debug.Log`, so I used `DebugX.Log` and logged only when something was marked.
- `Apparel.Name` and `Apparel.DisplayName` are assumed to be readable strings on `CC.scrObj_Apparel.Apparel`, which I did not see; `Apparel` is assumed non-null.
- The filtered list is rebuilt on every OnGUI from the loaded assets, and a pending project-change reload runs only on the Layout event, so the GUILayout pass stays consistent.
- The "Hidden" tag and the details line both use `IsManuallyHidden`, which is only reached for done items, matching the ManuallyHidden filter.
