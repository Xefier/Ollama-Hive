#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using System.Linq;
using UnityEditor;
using UnityEngine;
using LiminalLabs.CharacterCustomizer.Core;

namespace LiminalLabs.CharacterCustomizer
{
    /// <summary>Browses every apparel asset in the project and marks the ones still being made done in one go.</summary>
    public class ApparelEditorWindow : EditorWindow
    {
        private const float ListWidth = 320f;
        private static readonly Color SelectedRowBackground = new Color(0.24f, 0.48f, 0.90f, 0.35f);

        private enum StatusFilter
        {
            All,
            NotDone,
            Done,
            ManuallyHidden
        }

        private List<ApparelObj> apparelList = new();
        private Dictionary<string, ApparelObj> byAssetName = new();
        private ApparelObj selected;
        private Editor cachedEditor;

        private string search = string.Empty;
        private StatusFilter filter = StatusFilter.All;
        private int slotFilter = -1; // -1 = any slot
        private string[] slotNames = Enum.GetNames(typeof(ApparelSlot));

        private Vector2 listScroll;
        private Vector2 detailScroll;
        private bool needsReload;

        private readonly List<ApparelObj> shown = new();

        // Built lazily because the styles are copied: one instance per window, shared by every row
        private GUIStyle notDoneTagStyle;
        private GUIStyle hiddenTagStyle;

        [MenuItem("Tools/Character Customizer/Apparel Editor")]
        private static void Open() => GetWindow<ApparelEditorWindow>("Apparel Editor");

        private void OnEnable()
        {
            Reload();
            needsReload = false;
        }

        private void OnDisable()
        {
            if (cachedEditor != null) DestroyImmediate(cachedEditor);
            cachedEditor = null;
        }

        private void OnProjectChange()
        {
            needsReload = true;
            Repaint();
        }

        private void Reload()
        {
            // FindAssets is fine here: editor tooling, not runtime code
            string[] guids = AssetDatabase.FindAssets("t:ApparelObj");
            List<ApparelObj> loaded = new(guids.Length);
            foreach (string guid in guids)
            {
                var apparel = AssetDatabase.LoadAssetAtPath<ApparelObj>(AssetDatabase.GUIDToAssetPath(guid));
                if (apparel != null) loaded.Add(apparel);
            }

            // The filter keeps the selection when the list reloads if the same asset is still there
            string selectedPath = selected != null ? AssetDatabase.GetAssetPath(selected) : null;
            loaded.Sort((a, b) => string.CompareOrdinal(a.name, b.name));
            apparelList = loaded;
            byAssetName = new Dictionary<string, ApparelObj>(StringComparer.Ordinal);
            foreach (var apparel in apparelList)
                byAssetName.TryAdd(apparel.name, apparel);
            selected = selectedPath != null ? AssetDatabase.LoadAssetAtPath<ApparelObj>(selectedPath) : null;

            if (slotFilter >= slotNames.Length) slotFilter = -1;
            shown.Clear();
            listScroll = Vector2.zero;
        }

        private static bool IsManuallyHidden(ApparelObj apparel)
        {
            return !apparel.NotDone && (!apparel.UsableInCharacterCreator || (apparel.HiddenOnBodies != null && apparel.HiddenOnBodies.Length > 0));
        }

        private bool Matches(ApparelObj apparel)
        {
            if (search.Length > 0)
            {
                bool found = apparel.name.IndexOf(search, StringComparison.OrdinalIgnoreCase) >= 0
                             || (apparel.Apparel?.Name?.IndexOf(search, StringComparison.OrdinalIgnoreCase) ?? -1) >= 0
                             || (apparel.Apparel?.DisplayName?.IndexOf(search, StringComparison.OrdinalIgnoreCase) ?? -1) >= 0;
                if (!found) return false;
            }

            switch (filter)
            {
                case StatusFilter.NotDone:
                    if (!apparel.NotDone) return false;
                    break;
                case StatusFilter.Done:
                    if (apparel.NotDone) return false;
                    break;
                case StatusFilter.ManuallyHidden:
                    if (!IsManuallyHidden(apparel)) return false;
                    break;
            }

            return slotFilter < 0 || (apparel.Slots != null && apparel.Slots.Contains((ApparelSlot)slotFilter));
        }

        /// <summary>The rows the list shows now. Shared by the list and the toolbar, so both stay honest.</summary>
        private IReadOnlyList<ApparelObj> GetShown()
        {
            shown.Clear();
            foreach (var apparel in apparelList)
                if (Matches(apparel)) shown.Add(apparel);
            return shown;
        }

        private void MarkShownDone()
        {
            var shownApparel = GetShown();
            int notDone = shownApparel.Count(a => a.NotDone);
            if (notDone == 0) return;
            if (!EditorUtility.DisplayDialog("Mark apparel done", $"Mark {notDone} apparel done? They become visible to players.", "Mark done", "Cancel"))
                return;
            MarkDone(shownApparel, byAssetName);
        }

        /// <summary>
        /// Marks the given apparel done, together with every version of them (one per body, linked by name): a garment
        /// made for several bodies shares one status, so marking one done marks them all.
        /// </summary>
        private static void MarkDone(IEnumerable<ApparelObj> items, Dictionary<string, ApparelObj> byAssetName)
        {
            var toMark = new HashSet<ApparelObj>();
            foreach (var apparel in items)
            {
                toMark.Add(apparel);
                foreach (var version in ApparelCatalog.BodyVersionsOf(apparel.Apparel.Name))
                {
                    if (byAssetName.TryGetValue(version.AssetName, out var versionApparel)) toMark.Add(versionApparel);
                }
            }

            var marked = new List<string>();
            foreach (var apparel in toMark)
            {
                if (!apparel.NotDone) continue;
                Undo.RecordObject(apparel, "Mark apparel done");
                apparel.NotDone = false;
                EditorUtility.SetDirty(apparel);
                // One asset at a time: never SaveAssets(), the editor is shared
                AssetDatabase.SaveAssetIfDirty(apparel);
                marked.Add(apparel.name);
            }

            // Editor tooling may use Debug.Log
            Debug.Log($"[ApparelEditorWindow] Marked done: {string.Join(", ", marked)}");
        }

        private void DrawToolbar()
        {
            using (new EditorGUILayout.HorizontalScope(EditorStyles.toolbar))
            {
                search = EditorGUILayout.TextField(search, EditorStyles.toolbarSearchField, GUILayout.MinWidth(120));
                filter = (StatusFilter)EditorGUILayout.EnumPopup(filter, EditorStyles.toolbarPopup, GUILayout.Width(110));

                var slotOptions = new string[slotNames.Length + 1] { "Any slot" };
                slotNames.CopyTo(slotOptions, 1);
                slotFilter = EditorGUILayout.Popup(slotFilter, slotOptions, EditorStyles.toolbarPopup, GUILayout.Width(90));

                GUILayout.FlexibleSpace();

                var shownApparel = GetShown();
                GUILayout.Label($"{shownApparel.Count} of {apparelList.Count}", EditorStyles.miniLabel);

                using (new EditorGUI.DisabledScope(!shownApparel.Any(a => a.NotDone)))
                {
                    if (GUILayout.Button("Mark all shown done", EditorStyles.toolbarButton)) MarkShownDone();
                }

                if (GUILayout.Button("Refresh", EditorStyles.toolbarButton)) Reload();
            }
        }

        private static bool TryMoveSelection(IReadOnlyList<ApparelObj> shownApparel, int delta, out ApparelObj moved)
        {
            moved = null;
            if (shownApparel.Count == 0) return false;
            int index = shownApparel.IndexOf(Selection.activeObject as ApparelObj);
            int next = index < 0 ? (delta > 0 ? 0 : shownApparel.Count - 1) : Mathf.Clamp(index + delta, 0, shownApparel.Count - 1);
            moved = shownApparel[next];
            return index != next;
        }

        private void DrawList()
        {
            EditorGUILayout.BeginVertical(GUILayout.Width(ListWidth));
            listScroll = EditorGUILayout.BeginScrollView(listScroll);

            var shownApparel = GetShown();
            if (shownApparel.Count == 0)
            {
                GUILayout.Label("No apparel matches.");
            }
            else
            {
                foreach (var apparel in shownApparel)
                {
                    Rect row = EditorGUILayout.GetControlRect(false, 20);
                    if (apparel == selected) EditorGUI.DrawRect(row, SelectedRowBackground);

                    EditorGUILayout.LabelField(apparel.name, GUILayout.Width(row.width - 140));
                    EditorGUILayout.LabelField(apparel.Slots != null && apparel.Slots.Length > 0 ? apparel.Slots[0].ToString() : "-",
                        GUILayout.Width(70));

                    if (apparel.NotDone)
                    {
                        EditorGUILayout.LabelField("Not done", NotDoneTagStyle, GUILayout.Width(70), GUILayout.AlignFlag.AlignRight);
                    }
                    else if (IsManuallyHidden(apparel))
                    {
                        EditorGUILayout.LabelField("Hidden", HiddenTagStyle, GUILayout.Width(70), GUILayout.AlignFlag.AlignRight);
                    }
                    else
                    {
                        EditorGUILayout.LabelField(string.Empty, GUILayout.Width(70));
                    }

                    if (Event.current.type == EventType.MouseDown && row.Contains(Event.current.mousePosition))
                    {
                        selected = apparel;
                        Event.current.Use();
                        GUI.FocusControl(null); // keep the Up/Down keys for the selection, not the search field
                    }
                }
            }

            EditorGUILayout.EndScrollView();
            EditorGUILayout.EndVertical();
        }

        private void DrawDetails()
        {
            EditorGUILayout.BeginVertical();
            detailScroll = EditorGUILayout.BeginScrollView(detailScroll);

            if (selected == null)
            {
                EditorGUILayout.HelpBox("Select an apparel on the left.", MessageType.Info);
            }
            else
            {
                using (new EditorGUI.DisabledScope(true))
                {
                    EditorGUILayout.ObjectField("Asset", selected, typeof(ApparelObj), false);
                }

                if (selected.NotDone)
                {
                    EditorGUILayout.HelpBox("Not done yet: hidden from players on every body and never sold. Mark it done to show it.",
                        MessageType.Warning);
                    using (new EditorGUILayout.HorizontalScope())
                    {
                        GUILayout.FlexibleSpace();
                        if (GUILayout.Button("Mark done", GUILayout.Height(24))) MarkDone(new[] { selected }, byAssetName);
                        GUILayout.FlexibleSpace();
                    }
                }
                else
                {
                    EditorGUILayout.HelpBox(IsManuallyHidden(selected)
                        ? "Done: visible to players (but manually hidden: Usable In Character Creator is off or Hidden On Bodies is set)"
                        : "Done: visible to players", MessageType.Info);
                }

                using (new EditorGUILayout.HorizontalScope())
                {
                    if (GUILayout.Button("Ping")) EditorGUIUtility.PingObject(selected);
                    if (GUILayout.Button("Select in Project")) Selection.activeObject = selected;
                }

                Editor.CreateCachedEditor(selected, null, ref cachedEditor);
                if (cachedEditor != null) cachedEditor.OnInspectorGUI();
            }

            EditorGUILayout.EndScrollView();
            EditorGUILayout.EndVertical();
        }

        private void OnGUI()
        {
            if (needsReload)
            {
                needsReload = false;
                Reload();
            }

            var shownApparel = GetShown();
            if (Event.current.type == EventType.KeyDown && !string.IsNullOrEmpty(search) == false
                && TryMoveSelection(shownApparel, Event.current.keyCode == KeyCode.UpArrow ? -1 : Event.current.keyCode == KeyCode.DownArrow ? 1 : 0, out var moved))
            {
                selected = moved;
                Event.current.Use();
            }

            DrawToolbar();
            GUILayout.BeginHorizontal();
            DrawList();
            DrawDetails();
            GUILayout.EndHorizontal();
        }

        private GUIStyle NotDoneTagStyle
        {
            get
            {
                if (notDoneTagStyle == null)
                {
                    notDoneTagStyle = new GUIStyle(EditorStyles.miniLabel) { richText = false };
                    notDoneTagStyle.normal.textColor = new Color(1f, 0.6f, 0.2f);
                }
                return notDoneTagStyle;
            }
        }

        private GUIStyle HiddenTagStyle
        {
            get
            {
                if (hiddenTagStyle == null)
                {
                    hiddenTagStyle = new GUIStyle(EditorStyles.miniLabel) { richText = false };
                    hiddenTagStyle.normal.textColor = new Color(0.55f, 0.55f, 0.55f);
                }
                return hiddenTagStyle;
            }
        }
    }
}
#endif
