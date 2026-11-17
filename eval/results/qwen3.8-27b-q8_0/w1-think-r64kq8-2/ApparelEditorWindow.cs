// FILE: ApparelEditorWindow.cs
#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using UnityEditor;
using UnityEngine;

namespace LiminalLabs.CharacterCustomizer
{
    public class ApparelEditorWindow : EditorWindow
    {
        private enum StatusFilter { All, NotDone, Done, ManuallyHidden }

        private ApparelObj[] _apparel;
        private Dictionary<string, ApparelObj> _byAssetName;
        private ApparelObj[] _shown;
        private ApparelObj selected;

        private string search = "";
        private StatusFilter filter = StatusFilter.All;
        private int slotFilter; // 0 = Any slot, 1+ = slot index into Enum.GetNames

        private Vector2 listScroll;
        private Vector2 detailScroll;

        private Editor cachedEditor;
        private bool _needsReload;

        private GUIStyle _notDoneStyle;
        private GUIStyle _hiddenStyle;

        private static string[] _slotOptions;

        [MenuItem("Tools/Character Customizer/Apparel Editor")]
        private static void Open()
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
            _needsReload = true;
            Repaint();
        }

        private void Reload()
        {
            // FindAssets is acceptable here: editor-only tooling.
            var guids = AssetDatabase.FindAssets("t:ApparelObj");
            var list = new List<ApparelObj>(guids.Length);
            foreach (var guid in guids)
            {
                var path = AssetDatabase.GUIDToAssetPath(guid);
                var obj = AssetDatabase.LoadAssetAtPath<ApparelObj>(path);
                if (obj != null)
                    list.Add(obj);
            }

            list.Sort((a, b) => string.CompareOrdinal(a.name, b.name));
            _apparel = list.ToArray();

            _byAssetName = new Dictionary<string, ApparelObj>(_apparel.Length);
            foreach (var a in _apparel)
                _byAssetName[a.name] = a;

            // Preserve selection across reload if the same asset is still present.
            if (selected != null)
            {
                bool found = false;
                foreach (var a in _apparel)
                {
                    if (ReferenceEquals(a, selected)) { found = true; break; }
                }
                if (!found)
                    selected = null;
            }

            RebuildShown();
        }

        private void RebuildShown()
        {
            if (_apparel == null)
            {
                _shown = Array.Empty<ApparelObj>();
                return;
            }

            var shown = new List<ApparelObj>();
            foreach (var a in _apparel)
            {
                if (!MatchesSearch(a)) continue;
                if (!MatchesStatus(a)) continue;
                if (!MatchesSlot(a)) continue;
                shown.Add(a);
            }
            _shown = shown.ToArray();
        }

        private bool MatchesSearch(ApparelObj a)
        {
            if (string.IsNullOrEmpty(search)) return true;
            if (a.name != null && a.name.IndexOf(search, StringComparison.OrdinalIgnoreCase) >= 0) return true;
            var app = a.Apparel;
            if (app != null)
            {
                if (app.Name != null && app.Name.IndexOf(search, StringComparison.OrdinalIgnoreCase) >= 0) return true;
                if (app.DisplayName != null && app.DisplayName.IndexOf(search, StringComparison.OrdinalIgnoreCase) >= 0) return true;
            }
            return false;
        }

        private bool MatchesStatus(ApparelObj a)
        {
            switch (filter)
            {
                case StatusFilter.NotDone:
                    return a.NotDone;
                case StatusFilter.Done:
                    return !a.NotDone;
                case StatusFilter.ManuallyHidden:
                    return !a.NotDone && IsManuallyHidden(a);
                default:
                    return true;
            }
        }

        private static bool IsManuallyHidden(ApparelObj a)
        {
            return !a.UsableInCharacterCreator || (a.HiddenOnBodies != null && a.HiddenOnBodies.Length > 0);
        }

        private bool MatchesSlot(ApparelObj a)
        {
            if (slotFilter <= 0) return true;
            if (a.Slots == null) return false;
            var target = (ApparelSlot)(slotFilter - 1);
            for (int i = 0; i < a.Slots.Length; i++)
            {
                if (a.Slots[i] == target) return true;
            }
            return false;
        }

        private void OnGUI()
        {
            if (_needsReload)
            {
                _needsReload = false;
                Reload();
            }

            GUILayout.Space(4);
            DrawToolbar();
            GUILayout.Space(4);

            EditorGUILayout.BeginHorizontal();
            DrawList();
            DrawDetails();
            EditorGUILayout.EndHorizontal();
        }

        private void DrawToolbar()
        {
            EditorGUILayout.BeginHorizontal(EditorStyles.toolbar);

            search = EditorGUILayout.TextField(search, EditorStyles.toolbarSearchField, GUILayout.MinWidth(120));
            filter = (StatusFilter)EditorGUILayout.EnumPopup(filter, EditorStyles.toolbarPopup, GUILayout.Width(110));

            EnsureSlotOptions();
            slotFilter = EditorGUILayout.Popup(slotFilter, _slotOptions, EditorStyles.toolbarPopup, GUILayout.Width(90));

            GUILayout.FlexibleSpace();

            int shownCount = _shown != null ? _shown.Length : 0;
            int totalCount = _apparel != null ? _apparel.Length : 0;
            GUILayout.Label($"{shownCount} of {totalCount}", EditorStyles.miniLabel);

            bool anyNotDoneShown = false;
            if (_shown != null)
            {
                foreach (var a in _shown)
                {
                    if (a.NotDone) { anyNotDoneShown = true; break; }
                }
            }

            using (new EditorGUI.DisabledScope(!anyNotDoneShown))
            {
                if (GUILayout.Button("Mark all shown done", EditorStyles.toolbarButton))
                {
                    var notDoneShown = new List<ApparelObj>();
                    foreach (var a in _shown)
                        if (a.NotDone) notDoneShown.Add(a);

                    if (EditorUtility.DisplayDialog("Mark apparel done",
                        $"Mark {notDoneShown.Count} apparel done? They become visible to players.",
                        "Mark done", "Cancel"))
                    {
                        MarkDone(notDoneShown, _byAssetName);
                        Reload();
                    }
                }
            }

            if (GUILayout.Button("Refresh", EditorStyles.toolbarButton))
                Reload();

            EditorGUILayout.EndHorizontal();
        }

        private void DrawList()
        {
            EditorGUILayout.BeginVertical(GUILayout.Width(320));
            listScroll = EditorGUILayout.BeginScrollView(listScroll);

            if (_shown == null || _shown.Length == 0)
            {
                GUILayout.Label("No apparel matches.");
            }
            else
            {
                for (int i = 0; i < _shown.Length; i++)
                    DrawRow(_shown[i]);

                HandleArrowKeys();
            }

            EditorGUILayout.EndScrollView();
            EditorGUILayout.EndVertical();
        }

        private void DrawRow(ApparelObj apparel)
        {
            Rect row = EditorGUILayout.GetControlRect(false, 20);

            if (ReferenceEquals(apparel, selected))
                EditorGUI.DrawRect(row, new Color(0.24f, 0.48f, 0.90f, 0.35f));

            const float colW = 70f;

            // Name occupies the remaining width on the left.
            float nameW = row.width - colW * 2f - 8f;
            Rect nameRect = new Rect(row.x + 4f, row.y, nameW, row.height);
            EditorGUI.LabelField(nameRect, apparel.name);

            // Primary slot.
            Rect slotRect = new Rect(row.x + row.width - colW * 2f, row.y, colW, row.height);
            string slotText = apparel.Slots != null && apparel.Slots.Length > 0 ? apparel.Slots[0].ToString() : "-";
            EditorGUI.LabelField(slotRect, slotText, EditorStyles.miniLabel);

            // Status tag.
            Rect statusRect = new Rect(row.x + row.width - colW, row.y, colW, row.height);
            if (apparel.NotDone)
                EditorGUI.LabelField(statusRect, "Not done", GetNotDoneStyle());
            else if (IsManuallyHidden(apparel))
                EditorGUI.LabelField(statusRect, "Hidden", GetHiddenStyle());

            if (Event.current.type == EventType.MouseDown && row.Contains(Event.current.mousePosition))
            {
                selected = apparel;
                Event.current.Use();
                GUI.FocusControl(null);
            }
        }

        private void HandleArrowKeys()
        {
            if (Event.current.type != EventType.KeyDown) return;
            if (Event.current.keyCode != KeyCode.UpArrow && Event.current.keyCode != KeyCode.DownArrow) return;
            if (_shown == null || _shown.Length == 0) return;

            int idx = -1;
            for (int i = 0; i < _shown.Length; i++)
            {
                if (ReferenceEquals(_shown[i], selected)) { idx = i; break; }
            }

            if (Event.current.keyCode == KeyCode.UpArrow)
            {
                if (idx > 0)
                    selected = _shown[idx - 1];
            }
            else
            {
                if (idx < _shown.Length - 1)
                    selected = _shown[idx + 1];
            }

            Event.current.Use();
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
                    EditorGUILayout.HelpBox(
                        "Not done yet: hidden from players on every body and never sold. Mark it done to show it.",
                        MessageType.Warning);
                    if (GUILayout.Button("Mark done", GUILayout.Height(24)))
                    {
                        MarkDone(new[] { selected }, _byAssetName);
                        Reload();
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
                    EditorGUIUtility.PingObject(selected);
                if (GUILayout.Button("Select in Project"))
                    Selection.activeObject = selected;
                EditorGUILayout.EndHorizontal();

                Editor.CreateCachedEditor(selected, null, ref cachedEditor);
                if (cachedEditor != null)
                    cachedEditor.OnInspectorGUI();
            }

            EditorGUILayout.EndScrollView();
            EditorGUILayout.EndVertical();
        }

        private static void MarkDone(IEnumerable<ApparelObj> items, Dictionary<string, ApparelObj> byAssetName)
        {
            // A garment made for several bodies has one version per body, linked by name;
            // marking one done marks every version.
            var all = new HashSet<ApparelObj>();
            foreach (var item in items)
            {
                all.Add(item);
                var versions = ApparelCatalog.BodyVersionsOf(item.Apparel.Name);
                if (versions != null)
                {
                    foreach (var entry in versions)
                    {
                        if (byAssetName != null && byAssetName.TryGetValue(entry.AssetName, out var version))
                            all.Add(version);
                    }
                }
            }

            var markedNames = new List<string>();
            foreach (var a in all)
            {
                if (a.NotDone)
                {
                    Undo.RecordObject(a, "Mark apparel done");
                    a.NotDone = false;
                    EditorUtility.SetDirty(a);
                    AssetDatabase.SaveAssetIfDirty(a);
                    markedNames.Add(a.name);
                }
            }

            // Editor tooling may use Debug.Log directly.
            if (markedNames.Count > 0)
                Debug.Log($"[ApparelEditorWindow] Marked done: {string.Join(", ", markedNames)}");
        }

        private static void EnsureSlotOptions()
        {
            if (_slotOptions != null) return;
            var names = Enum.GetNames(typeof(ApparelSlot));
            _slotOptions = new string[names.Length + 1];
            _slotOptions[0] = "Any slot";
            for (int i = 0; i < names.Length; i++)
                _slotOptions[i + 1] = names[i];
        }

        private GUIStyle GetNotDoneStyle()
        {
            if (_notDoneStyle == null)
            {
                _notDoneStyle = new GUIStyle(EditorStyles.miniLabel);
                _notDoneStyle.normal.textColor = new Color(1f, 0.6f, 0.2f);
            }
            return _notDoneStyle;
        }

        private GUIStyle GetHiddenStyle()
        {
            if (_hiddenStyle == null)
            {
                _hiddenStyle = new GUIStyle(EditorStyles.miniLabel);
                _hiddenStyle.normal.textColor = new Color(0.55f, 0.55f, 0.55f);
            }
            return _hiddenStyle;
        }
    }
}
#endif
