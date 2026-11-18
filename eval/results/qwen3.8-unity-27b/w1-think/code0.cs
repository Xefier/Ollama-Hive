#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using UnityEditor;
using UnityEngine;

namespace LiminalLabs.CharacterCustomizer
{
    /// <summary>
    /// Browses every ApparelObj in the project and edits it: search and filter on the left, the selected asset's own
    /// inspector on the right (with its Not-done status up top), and "Mark done" on one or on all shown at once.
    /// </summary>
    public class ApparelEditorWindow : EditorWindow
    {
        private const string NotDoneTag = "Not done";
        private const string HiddenTag = "Hidden";
        private const float NotSelectedColor = 0.30f;
        private static readonly Color SelectedColor = new Color(0.24f, 0.48f, 0.90f, 0.35f);

        private enum StatusFilter
        {
            All,
            NotDone,
            Done,
            ManuallyHidden
        }

        private readonly List<ApparelObj> all = new List<ApparelObj>(); // everything loaded, by name
        private readonly List<ApparelObj> shown = new List<ApparelObj>(); // the filtered order the list shows, newest first

        private ApparelObj selected;
        private string search = string.Empty;
        private StatusFilter filter;
        private int slotFilter; // index into SlotFilterOptions: 0 = any slot
        private Vector2 listScroll;
        private Vector2 detailScroll;
        private Editor cachedEditor; // the selected asset's inspector (CreateCachedEditor), destroyed in OnDisable

        private Dictionary<string, ApparelObj> byAssetName; // asset name -> loaded ApparelObj, for MarkDone's versions
        private bool pendingReload; // OnProjectChange: reload at the next OnGUI

        // Built once, not every OnGUI (a GUIStyle copies its normal state by reference, so the color stays set)
        private GUIStyle notDoneStyle;
        private GUIStyle hiddenStyle;
        private string[] slotOptions;

        [MenuItem("Tools/Character Customizer/Apparel Editor")]
        private static void Open()
        {
            GetWindow<ApparelEditorWindow>("Apparel Editor");
        }

        private void OnEnable()
        {
            LoadAll();
        }

        // An EditorWindow message: the project changed (import, etc.), so the list may be stale
        private void OnProjectChange()
        {
            pendingReload = true;
            Repaint();
        }

        private void OnDisable()
        {
            if (cachedEditor != null)
            {
                DestroyImmediate(cachedEditor);
                cachedEditor = null;
            }
        }

        private void OnGUI()
        {
            if (pendingReload)
            {
                pendingReload = false;
                LoadAll();
            }

            RebuildShown();

            DrawToolbar();

            GUILayout.BeginHorizontal();
            DrawList();
            DrawDetails();
            GUILayout.EndHorizontal();
        }

        // ------------------------------------------------------------------ loading

        private void LoadAll()
        {
            var keep = selected != null ? AssetDatabase.GetAssetPath(selected) : null;
            // FindAssets is fine here: editor tooling, not runtime
            var guids = AssetDatabase.FindAssets("t:ApparelObj");
            all.Clear();
            byAssetName = new Dictionary<string, ApparelObj>();
            foreach (var guid in guids)
            {
                var asset = AssetDatabase.LoadAssetAtPath<ApparelObj>(AssetDatabase.GUIDToAssetPath(guid));
                if (asset == null) continue; // placeholder or a broken link
                all.Add(asset);
                byAssetName[asset.name] = asset;
            }

            all.Sort((a, b) => string.CompareOrdinal(a.name, b.name));

            if (keep != null)
            {
                selected = null;
                foreach (var asset in all)
                    if (AssetDatabase.GetAssetPath(asset) == keep)
                    {
                        selected = asset;
                        break;
                    }
            }
        }

        // "Any slot" followed by every ApparelSlot name, in declaration order
        private string[] SlotFilterOptions
        {
            get
            {
                if (slotOptions == null)
                {
                    var names = Enum.GetNames(typeof(ApparelSlot));
                    slotOptions = new string[names.Length + 1];
                    slotOptions[0] = "Any slot";
                    for (var i = 0; i < names.Length; i++) slotOptions[i + 1] = names[i];
                }

                return slotOptions;
            }
        }

        private void RebuildShown()
        {
            shown.Clear();
            foreach (var asset in all)
                if (MatchesSearch(asset) && MatchesStatus(asset) && MatchesSlot(asset))
                    shown.Add(asset);
        }

        private static bool MatchesSearch(ApparelObj asset)
        {
            return string.IsNullOrEmpty(search)
                   || Contains(asset.name, search)
                   || Contains(asset.Apparel != null ? asset.Apparel.Name : null, search)
                   || Contains(asset.Apparel != null ? asset.Apparel.DisplayName : null, search);
        }

        private static bool Contains(string text, string search)
        {
            return text != null && text.IndexOf(search, StringComparison.OrdinalIgnoreCase) >= 0;
        }

        private static bool MatchesStatus(ApparelObj asset)
        {
            switch (filter)
            {
                case StatusFilter.NotDone:
                    return asset.NotDone;
                case StatusFilter.Done:
                    return !asset.NotDone;
                // Not-done is its own state, so it never shows here as well
                case StatusFilter.ManuallyHidden:
                    return !asset.NotDone && IsManuallyHidden(asset);
                default:
                    return true;
            }
        }

        private bool MatchesSlot(ApparelObj asset)
        {
            if (slotFilter <= 0) return true;
            var slot = (ApparelSlot)Enum.Parse(typeof(ApparelSlot), SlotFilterOptions[slotFilter]);
            var slots = asset.Slots;
            if (slots == null) return false;
            foreach (var s in slots)
                if (s == slot) return true;
            return false;
        }

        private static bool IsManuallyHidden(ApparelObj asset)
        {
            return !asset.UsableInCharacterCreator || (asset.HiddenOnBodies != null && asset.HiddenOnBodies.Length > 0);
        }

        // ------------------------------------------------------------------ toolbar

        private void DrawToolbar()
        {
            GUILayout.BeginHorizontal(EditorStyles.toolbar);

            search = EditorGUILayout.TextField(search, EditorStyles.toolbarSearchField, GUILayout.MinWidth(120));

            filter = (StatusFilter)EditorGUILayout.EnumPopup(filter, EditorStyles.toolbarPopup, GUILayout.Width(110));

            slotFilter = EditorGUILayout.Popup(slotFilter, SlotFilterOptions, EditorStyles.toolbarPopup, GUILayout.Width(90));

            GUILayout.FlexibleSpace();

            GUILayout.Label($"{shown.Count} of {all.Count}", EditorStyles.miniLabel);

            var anyNotDoneShown = false;
            foreach (var asset in shown)
                if (asset.NotDone)
                {
                    anyNotDoneShown = true;
                    break;
                }

            using (new EditorGUI.DisabledScope(!anyNotDoneShown))
            {
                if (GUILayout.Button("Mark all shown done", EditorStyles.toolbarButton))
                    MarkAllShownDone();
            }

            if (GUILayout.Button("Refresh", EditorStyles.toolbarButton))
                LoadAll();

            GUILayout.EndHorizontal();
        }

        private void MarkAllShownDone()
        {
            var count = 0;
            foreach (var asset in shown)
                if (asset.NotDone) count++;
            if (count == 0) return;

            if (!EditorUtility.DisplayDialog("Mark apparel done", $"Mark {count} apparel done? They become visible to players.", "Mark done", "Cancel"))
                return;

            var notDone = new List<ApparelObj>();
            foreach (var asset in shown)
                if (asset.NotDone) notDone.Add(asset);
            MarkDone(notDone, byAssetName);
        }

        // ------------------------------------------------------------------ list

        private void DrawList()
        {
            GUILayout.BeginVertical(GUILayout.Width(320));
            listScroll = EditorGUILayout.BeginScrollView(listScroll);

            if (shown.Count == 0)
            {
                GUILayout.Label("No apparel matches.");
            }
            else
            {
                foreach (var asset in shown)
                    DrawRow(asset);
                HandleArrowKeys();
            }

            EditorGUILayout.EndScrollView();
            GUILayout.EndVertical();
        }

        private void DrawRow(ApparelObj asset)
        {
            var row = EditorGUILayout.GetControlRect(false, 20);

            if (selected == asset)
                EditorGUI.DrawRect(row, SelectedColor);

            if (Event.current.type == EventType.MouseDown && row.Contains(Event.current.mousePosition))
            {
                selected = asset;
                Event.current.Use();
                GUI.FocusControl(null);
            }

            // three columns: the name (the rest of the row), the primary slot, and a status tag at the right end
            const float slotWidth = 70f;
            const float tagWidth = 70f;
            var x = row.x + 2f;
            var nameWidth = Mathf.Max(20f, row.width - slotWidth - tagWidth);

            EditorGUI.LabelField(new Rect(x, row.y, nameWidth, row.height), asset.name);
            EditorGUI.LabelField(new Rect(x + nameWidth, row.y, slotWidth, row.height), PrimarySlotText(asset), EditorStyles.miniLabel);

            var tag = asset.NotDone ? NotDoneTag : IsManuallyHidden(asset) ? HiddenTag : null;
            if (tag != null)
            {
                var style = tag == NotDoneTag ? NotDoneTagStyle : HiddenTagStyle;
                GUI.Label(new Rect(row.x + row.width - tagWidth, row.y, tagWidth, row.height), tag, style);
            }
        }

        // Up/down move the selection through the shown list while the window has focus
        private void HandleArrowKeys()
        {
            var e = Event.current;
            if (e.type != EventType.KeyDown || shown.Count == 0) return;
            if (e.keyCode != KeyCode.UpArrow && e.keyCode != KeyCode.DownArrow) return;

            var i = shown.IndexOf(selected);
            var next = i < 0
                ? (e.keyCode == KeyCode.UpArrow ? shown.Count - 1 : 0)
                : e.keyCode == KeyCode.UpArrow ? i - 1 : i + 1;
            if (next < 0) next = 0;
            if (next >= shown.Count) next = shown.Count - 1;

            if (next != i)
            {
                selected = shown[next];
                e.Use();
            }
        }

        private static string PrimarySlotText(ApparelObj asset)
        {
            var slots = asset.Slots;
            return slots != null && slots.Length > 0 ? slots[0].ToString() : "-";
        }

        private GUIStyle NotDoneTagStyle
        {
            get
            {
                if (notDoneStyle == null)
                    notDoneStyle = new GUIStyle(EditorStyles.miniLabel) { normal = { textColor = new Color(1f, 0.6f, 0.2f) } };
                return notDoneStyle;
            }
        }

        private GUIStyle HiddenTagStyle
        {
            get
            {
                if (hiddenStyle == null)
                    hiddenStyle = new GUIStyle(EditorStyles.miniLabel) { normal = { textColor = Color.gray } };
                return hiddenStyle;
            }
        }

        // ------------------------------------------------------------------ details

        private void DrawDetails()
        {
            GUILayout.BeginVertical();
            detailScroll = EditorGUILayout.BeginScrollView(detailScroll);

            if (selected == null)
                EditorGUILayout.HelpBox("Select an apparel on the left.", MessageType.Info);
            else
                DrawDetailsFor(selected);

            EditorGUILayout.EndScrollView();
            GUILayout.EndVertical();
        }

        private void DrawDetailsFor(ApparelObj asset)
        {
            using (new EditorGUI.DisabledScope(true))
                EditorGUILayout.ObjectField("Asset", asset, typeof(ApparelObj), false);

            if (asset.NotDone)
            {
                EditorGUILayout.HelpBox("Not done yet: hidden from players on every body and never sold. Mark it done to show it.", MessageType.Warning);
                if (GUILayout.Button("Mark done", GUILayout.Height(24)))
                    MarkDone(new[] { asset }, byAssetName);
            }
            else
            {
                EditorGUILayout.HelpBox("Done: visible to players"
                                       + (IsManuallyHidden(asset) ? " (but manually hidden: Usable In Character Creator is off or Hidden On Bodies is set)" : string.Empty),
                                       MessageType.Info);
            }

            GUILayout.BeginHorizontal();
            if (GUILayout.Button("Ping"))
                EditorGUIUtility.PingObject(asset);
            if (GUILayout.Button("Select in Project"))
                Selection.activeObject = asset;
            GUILayout.EndHorizontal();

            Editor.CreateCachedEditor(asset, null, ref cachedEditor);
            cachedEditor.OnInspectorGUI(); // records undo and dirties the asset itself; nothing extra to do
        }

        // ------------------------------------------------------------------ marking done

        /// <summary>
        /// Marks the given apparel done, together with the other versions of the same garment when there are any: a
        /// garment made for several bodies has one version per body, named the same, and they share one status, so they
        /// all switch together (not just the one picked).
        /// </summary>
        private static void MarkDone(IEnumerable<ApparelObj> items, Dictionary<string, ApparelObj> byAssetName)
        {
            var toMark = new HashSet<ApparelObj>();
            var namesAsked = new HashSet<string>();

            foreach (var item in items)
            {
                toMark.Add(item);

                // BodyVersionsOf takes the apparel's name (AssetName for every version); the asset's own name is not needed
                var name = item.Apparel != null ? item.Apparel.Name : null;
                if (name != null && namesAsked.Add(name))
                {
                    foreach (var version in ApparelCatalog.BodyVersionsOf(name))
                    {
                        if (version.AssetName != null && byAssetName.TryGetValue(version.AssetName, out var asset))
                            toMark.Add(asset);
                    }
                }
            }

            var marked = new List<string>();
            foreach (var asset in toMark)
            {
                if (!asset.NotDone) continue;
                Undo.RecordObject(asset, "Mark apparel done");
                asset.NotDone = false;
                EditorUtility.SetDirty(asset);
                AssetDatabase.SaveAssetIfDirty(asset); // each one alone: never AssetDatabase.SaveAssets(), the editor is shared
                marked.Add(asset.name);
            }

            if (marked.Count > 0)
                Debug.Log($"[ApparelEditorWindow] Marked done: {string.Join(", ", marked)}"); // editor tooling may use Debug.Log
        }
    }
}
#endif
