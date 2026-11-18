// FILE: ApparelEditorWindow.cs
#if UNITY_EDITOR

using System;
using System.Collections.Generic;
using System.Linq;
using UnityEditor;
using UnityEngine;

namespace LiminalLabs.CharacterCustomizer
{
    /// <summary>Browses every ApparelObj in the project and edits its NotDone flag and other fields in place.</summary>
    public class ApparelEditorWindow : EditorWindow
    {
        private enum StatusFilter
        {
            All,
            NotDone,
            Done,
            ManuallyHidden
        }

        private const float ListWidth = 320f;
        private const float TagWidth = 70f;
        private const float SlotWidth = 70f;

        private static readonly string[] SlotFilterOptions;

        static ApparelEditorWindow()
        {
            var names = Enum.GetNames(typeof(ApparelSlot));
            SlotFilterOptions = new string[names.Length + 1];
            SlotFilterOptions[0] = "Any slot";
            for (int i = 0; i < names.Length; i++) SlotFilterOptions[i + 1] = names[i];
        }

        private List<ApparelObj> apparel = new List<ApparelObj>();
        private Dictionary<string, ApparelObj> byAssetName = new Dictionary<string, ApparelObj>();
        private readonly List<ApparelObj> shown = new List<ApparelObj>();
        private ApparelObj selected;
        private Editor cachedEditor;

        private string search = string.Empty;
        private StatusFilter filter;
        private int slotFilterIndex;

        private Vector2 listScroll;
        private Vector2 detailScroll;

        private bool needsReload;

        private GUIStyle notDoneTagStyle;
        private GUIStyle hiddenTagStyle;

        [MenuItem("Tools/Character Customizer/Apparel Editor")]
        private static void Open()
        {
            var window = GetWindow<ApparelEditorWindow>("Apparel Editor");
            window.Show();
        }

        private void OnEnable()
        {
            LoadApparel();
        }

        private void OnDisable()
        {
            if (cachedEditor != null) DestroyImmediate(cachedEditor);
            cachedEditor = null;
        }

        // An EditorWindow message: the project changed (import, create, delete). Reload on the next OnGUI so we do not reload in the middle of layout.
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
                LoadApparel();
            }

            BuildShown();
            DrawToolbar();
            HandleArrowKeys();

            EditorGUILayout.BeginHorizontal();
            DrawList();
            DrawDetails();
            EditorGUILayout.EndHorizontal();
        }

        // FindAssets is fine here: editor tooling, not runtime.
        private void LoadApparel()
        {
            var paths = AssetDatabase.FindAssets("t:ApparelObj");

            string prevPath = selected != null ? AssetDatabase.GetAssetPath(selected) : null;

            var list = new List<ApparelObj>(paths.Length);
            var byName = new Dictionary<string, ApparelObj>(paths.Length);
            foreach (var path in paths)
            {
                var asset = AssetDatabase.LoadAssetAtPath<ApparelObj>(path);
                if (asset == null) continue;
                list.Add(asset);
                byName[asset.name] = asset;
            }

            list.Sort((a, b) => string.CompareOrdinal(a.name, b.name));
            apparel = list;
            byAssetName = byName;

            if (prevPath != null)
            {
                var reload = AssetDatabase.LoadAssetAtPath<ApparelObj>(prevPath);
                selected = reload != null && list.Contains(reload) ? reload : null;
            }
        }

        private void BuildShown()
        {
            shown.Clear();
            foreach (var a in apparel)
            {
                if (MatchesSearch(a) && MatchesStatus(a) && MatchesSlot(a)) shown.Add(a);
            }
        }

        private bool MatchesSearch(ApparelObj a)
        {
            if (string.IsNullOrEmpty(search)) return true;
            return ContainsCI(a.name, search)
                || ContainsCI(a.Apparel?.Name, search)
                || ContainsCI(a.Apparel?.DisplayName, search);
        }

        private static bool ContainsCI(string text, string search)
        {
            return text != null && text.IndexOf(search, StringComparison.OrdinalIgnoreCase) >= 0;
        }

        private bool MatchesStatus(ApparelObj a)
        {
            switch (filter)
            {
                case StatusFilter.NotDone: return a.NotDone;
                case StatusFilter.Done: return !a.NotDone;
                case StatusFilter.ManuallyHidden: return !a.NotDone && IsManuallyHidden(a);
                default: return true;
            }
        }

        private static bool IsManuallyHidden(ApparelObj a)
        {
            return !a.UsableInCharacterCreator || (a.HiddenOnBodies != null && a.HiddenOnBodies.Length > 0);
        }

        private bool MatchesSlot(ApparelObj a)
        {
            if (slotFilterIndex <= 0) return true;
            var slot = (ApparelSlot)(slotFilterIndex - 1);
            if (a.Slots == null) return false;
            foreach (var s in a.Slots)
            {
                if (s == slot) return true;
            }

            return false;
        }

        // ── toolbar ──────────────────────────────────────────────────────────────────────────────────────────────

        private void DrawToolbar()
        {
            EditorGUILayout.BeginHorizontal(EditorStyles.toolbar);

            search = EditorGUILayout.TextField(search, EditorStyles.toolbarSearchField, GUILayout.MinWidth(120));
            filter = (StatusFilter)EditorGUILayout.EnumPopup(filter, EditorStyles.toolbarPopup, GUILayout.Width(110));
            slotFilterIndex = EditorGUILayout.Popup(slotFilterIndex, SlotFilterOptions, EditorStyles.toolbarPopup, GUILayout.Width(90));

            GUILayout.FlexibleSpace();
            GUILayout.Label($"{shown.Count} of {apparel.Count}", EditorStyles.miniLabel);

            bool anyNotDoneShown = shown.Any(a => a.NotDone);
            using (new EditorGUI.DisabledScope(!anyNotDoneShown))
            {
                if (GUILayout.Button("Mark all shown done", EditorStyles.toolbarButton))
                {
                    int count = shown.Count(a => a.NotDone);
                    if (EditorUtility.DisplayDialog("Mark apparel done",
                            $"Mark {count} apparel done? They become visible to players.", "Mark done", "Cancel"))
                    {
                        MarkDone(shown, byAssetName);
                        Repaint();
                    }
                }
            }

            if (GUILayout.Button("Refresh", EditorStyles.toolbarButton))
                LoadApparel();

            EditorGUILayout.EndHorizontal();
        }

        // ── keyboard ─────────────────────────────────────────────────────────────────────────────────────────────

        private void HandleArrowKeys()
        {
            var e = Event.current;
            if (e.type != EventType.KeyDown) return;
            if (e.keyCode != KeyCode.UpArrow && e.keyCode != KeyCode.DownArrow) return;
            if (shown.Count == 0 || selected == null) return;

            int index = shown.IndexOf(selected);
            if (index < 0) return;

            index += e.keyCode == KeyCode.UpArrow ? -1 : 1;
            if (index < 0 || index >= shown.Count) return;

            selected = shown[index];
            e.Use();
            GUI.FocusControl(null);
        }

        // ── list (left pane) ─────────────────────────────────────────────────────────────────────────────────────

        private void DrawList()
        {
            EditorGUILayout.BeginVertical(GUILayout.Width(ListWidth));
            listScroll = EditorGUILayout.BeginScrollView(listScroll);

            if (shown.Count == 0)
            {
                GUILayout.Label("No apparel matches.");
            }
            else
            {
                foreach (var a in shown)
                    DrawRow(a);
            }

            EditorGUILayout.EndScrollView();
            EditorGUILayout.EndVertical();
        }

        private void DrawRow(ApparelObj a)
        {
            Rect row = EditorGUILayout.GetControlRect(false, 20);

            if (a == selected)
                EditorGUI.DrawRect(row, new Color(0.24f, 0.48f, 0.90f, 0.35f));

            float nameWidth = row.width - SlotWidth - TagWidth;
            EditorGUI.LabelField(new Rect(row.x, row.y, nameWidth, row.height), a.name);

            string slotText = a.Slots != null && a.Slots.Length > 0 ? a.Slots[0].ToString() : "-";
            EditorGUI.LabelField(new Rect(row.x + nameWidth, row.y, SlotWidth, row.height), slotText);

            DrawTag(row, a);

            if (Event.current.type == EventType.MouseDown && row.Contains(Event.current.mousePosition))
            {
                selected = a;
                Event.current.Use();
                GUI.FocusControl(null);
            }
        }

        private void DrawTag(Rect row, ApparelObj a)
        {
            Rect tagRect = new Rect(row.x + row.width - TagWidth, row.y, TagWidth, row.height);
            if (a.NotDone)
            {
                if (notDoneTagStyle == null)
                {
                    notDoneTagStyle = new GUIStyle(EditorStyles.miniLabel);
                    notDoneTagStyle.normal.textColor = new Color(1f, 0.6f, 0.2f);
                }

                EditorGUI.Label(tagRect, "Not done", notDoneTagStyle);
            }
            else if (IsManuallyHidden(a))
            {
                if (hiddenTagStyle == null)
                {
                    hiddenTagStyle = new GUIStyle(EditorStyles.miniLabel);
                    hiddenTagStyle.normal.textColor = new Color(0.55f, 0.55f, 0.55f);
                }

                EditorGUI.Label(tagRect, "Hidden", hiddenTagStyle);
            }
        }

        // ── details (right pane) ─────────────────────────────────────────────────────────────────────────────────

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
                    EditorGUILayout.ObjectField("Asset", selected, typeof(ApparelObj), false);

                if (selected.NotDone)
                {
                    EditorGUILayout.HelpBox("Not done yet: hidden from players on every body and never sold. Mark it done to show it.", MessageType.Warning);
                    if (GUILayout.Button("Mark done", GUILayout.Height(24)))
                    {
                        MarkDone(new[] { selected }, byAssetName);
                        Repaint();
                    }
                }
                else
                {
                    string text = IsManuallyHidden(selected)
                        ? "Done: visible to players (but manually hidden: Usable In Character Creator is off or Hidden On Bodies is set)"
                        : "Done: visible to players";
                    EditorGUILayout.HelpBox(text, MessageType.Info);
                }

                EditorGUILayout.BeginHorizontal();
                if (GUILayout.Button("Ping"))
                    EditorGUIUtility.PingObject(selected);
                if (GUILayout.Button("Select in Project"))
                    Selection.activeObject = selected;
                EditorGUILayout.EndHorizontal();

                Editor.CreateCachedEditor(selected, null, ref cachedEditor);
                cachedEditor.OnInspectorGUI();
            }

            EditorGUILayout.EndScrollView();
            EditorGUILayout.EndVertical();
        }

        // ── marking done ─────────────────────────────────────────────────────────────────────────────────────────

        private static void MarkDone(IEnumerable<ApparelObj> items, Dictionary<string, ApparelObj> byAssetName)
        {
            // A garment made for several bodies has one version per body, linked by name; they share one status.
            var itemArray = items as IList<ApparelObj> ?? items.ToList();
            var all = new HashSet<ApparelObj>(itemArray);
            foreach (var item in itemArray)
            {
                foreach (var entry in ApparelCatalog.BodyVersionsOf(item.Apparel.Name))
                {
                    if (byAssetName.TryGetValue(entry.AssetName, out var version) && version != null)
                        all.Add(version);
                }
            }

            var marked = new List<string>();
            foreach (var a in all)
            {
                if (!a.NotDone) continue;
                Undo.RecordObject(a, "Mark apparel done");
                a.NotDone = false;
                EditorUtility.SetDirty(a);
                // Each asset saved alone: never AssetDatabase.SaveAssets(), the editor is shared.
                AssetDatabase.SaveAssetIfDirty(a);
                marked.Add(a.name);
            }

            if (marked.Count > 0)
                Debug.Log($"[ApparelEditorWindow] Marked done: {string.Join(", ", marked)}");
        }
    }
}

#endif
