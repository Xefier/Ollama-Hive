#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using UnityEditor;
using UnityEngine;

namespace LiminalLabs.CharacterCustomizer
{
    /// <summary>
    /// A browser for the project's apparel assets: search and filter them on the left, edit the selected one on the
    /// right, and mark them done (NotDone off), one at a time or all the shown ones together. A garment made for
    /// several bodies has one version per body, linked by name, and they share one status, so marking one marks every
    /// version.
    /// </summary>
    public class ApparelEditorWindow : EditorWindow
    {
        private enum StatusFilter { All, NotDone, Done, ManuallyHidden }

        private static readonly Color SelectedRowColor = new Color(0.24f, 0.48f, 0.90f, 0.35f);
        private static string[] slotOptions;
        private static GUIStyle tagNotDone;
        private static GUIStyle tagHidden;

        private List<ApparelObj> apparel = new List<ApparelObj>();
        private Dictionary<string, ApparelObj> byAssetName = new Dictionary<string, ApparelObj>();
        private ApparelObj selected;
        private Editor cachedEditor;
        private bool needReload;
        private string search = "";
        private StatusFilter filter;
        private int slotFilterIndex;
        private Vector2 listScroll;
        private Vector2 detailScroll;

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
            if (cachedEditor != null) DestroyImmediate(cachedEditor);
        }

        // An EditorWindow message, not UnityEvent: the flag is read and the reload happens in OnGUI
        private void OnProjectChange()
        {
            needReload = true;
            Repaint();
        }

        private void OnGUI()
        {
            if (needReload)
            {
                needReload = false;
                Reload();
            }

            var shown = Shown();
            DrawToolbar(shown);
            EditorGUILayout.BeginHorizontal();
            DrawList(shown);
            DrawDetails();
            EditorGUILayout.EndHorizontal();
        }

        private void Reload()
        {
            var keep = selected;
            // FindAssets is fine here: editor tooling, not a runtime call
            var guids = AssetDatabase.FindAssets("t:ApparelObj");
            var found = new List<ApparelObj>(guids.Length);
            foreach (var guid in guids)
            {
                var asset = AssetDatabase.LoadAssetAtPath<ApparelObj>(AssetDatabase.GUIDToAssetPath(guid));
                if (asset != null) found.Add(asset);
            }
            found.Sort((x, y) => string.CompareOrdinal(x.name, y.name));
            apparel = found;

            byAssetName = new Dictionary<string, ApparelObj>();
            foreach (var a in apparel)
            {
                if (!byAssetName.ContainsKey(a.name)) byAssetName.Add(a.name, a);
            }

            var shown = Shown();
            selected = keep != null && shown.Contains(keep) ? keep : null;
            Repaint();
        }

        private List<ApparelObj> Shown()
        {
            var shown = new List<ApparelObj>();
            foreach (var a in apparel)
            {
                if (Matches(a)) shown.Add(a);
            }
            return shown;
        }

        private bool Matches(ApparelObj a)
        {
            switch (filter)
            {
                case StatusFilter.NotDone:
                    if (!a.NotDone) return false;
                    break;
                case StatusFilter.Done:
                    if (a.NotDone) return false;
                    break;
                case StatusFilter.ManuallyHidden:
                    if (!IsManuallyHidden(a)) return false;
                    break;
            }
            if (!MatchesSearch(a)) return false;
            return slotFilterIndex == 0 || (a.Slots != null && Array.IndexOf(a.Slots, (ApparelSlot)(slotFilterIndex - 1)) >= 0);
        }

        private bool MatchesSearch(ApparelObj a)
        {
            if (string.IsNullOrEmpty(search)) return true;
            return Contains(a.name, search) || (a.Apparel != null && (Contains(a.Apparel.Name, search) || Contains(a.Apparel.DisplayName, search)));
        }

        private static bool Contains(string text, string search)
        {
            return text != null && text.IndexOf(search, StringComparison.OrdinalIgnoreCase) >= 0;
        }

        private static bool IsManuallyHidden(ApparelObj a)
        {
            return !a.NotDone && (!a.UsableInCharacterCreator || (a.HiddenOnBodies != null && a.HiddenOnBodies.Length > 0));
        }

        private void DrawToolbar(List<ApparelObj> shown)
        {
            EditorGUILayout.BeginHorizontal(EditorStyles.toolbar);
            search = EditorGUILayout.TextField(search, EditorStyles.toolbarSearchField, GUILayout.MinWidth(120));
            filter = (StatusFilter)EditorGUILayout.EnumPopup(filter, EditorStyles.toolbarPopup, GUILayout.Width(110));
            slotFilterIndex = EditorGUILayout.Popup(slotFilterIndex, SlotOptions, EditorStyles.toolbarPopup, GUILayout.Width(90));
            GUILayout.FlexibleSpace();
            GUILayout.Label($"{shown.Count} of {apparel.Count}", EditorStyles.miniLabel);
            using (new EditorGUI.DisabledScope(!AnyNotDone(shown)))
            {
                if (GUILayout.Button("Mark all shown done", EditorStyles.toolbarButton))
                {
                    var notDone = new List<ApparelObj>();
                    foreach (var a in shown)
                    {
                        if (a.NotDone) notDone.Add(a);
                    }
                    if (EditorUtility.DisplayDialog("Mark apparel done", $"Mark {notDone.Count} apparel done? They become visible to players.", "Mark done", "Cancel"))
                        MarkAndReload(notDone);
                }
            }
            if (GUILayout.Button("Refresh", EditorStyles.toolbarButton)) Reload();
            EditorGUILayout.EndHorizontal();
        }

        private static bool AnyNotDone(List<ApparelObj> shown)
        {
            foreach (var a in shown)
            {
                if (a.NotDone) return true;
            }
            return false;
        }

        private void DrawList(List<ApparelObj> shown)
        {
            EditorGUILayout.BeginVertical(GUILayout.Width(320));
            listScroll = EditorGUILayout.BeginScrollView(listScroll);
            if (shown.Count == 0)
            {
                GUILayout.Label("No apparel matches.");
            }
            else
            {
                MoveSelection(shown);
                foreach (var a in shown) DrawRow(a);
            }
            EditorGUILayout.EndScrollView();
            EditorGUILayout.EndVertical();
        }

        private void MoveSelection(List<ApparelObj> shown)
        {
            if (Event.current.type != EventType.KeyDown || selected == null || !shown.Contains(selected)) return;
            var move = Event.current.keyCode == KeyCode.UpArrow ? -1 : Event.current.keyCode == KeyCode.DownArrow ? 1 : 0;
            if (move == 0) return;
            var index = shown.IndexOf(selected) + move;
            if (index < 0 || index >= shown.Count) return;
            selected = shown[index];
            Event.current.Use();
            GUI.FocusControl(null);
        }

        private void DrawRow(ApparelObj a)
        {
            Rect row = EditorGUILayout.GetControlRect(false, 20);
            if (a == selected) EditorGUI.DrawRect(row, SelectedRowColor);

            if (Event.current.type == EventType.MouseDown && row.Contains(Event.current.mousePosition))
            {
                selected = a;
                Event.current.Use();
                GUI.FocusControl(null);
            }

            var slotText = a.Slots != null && a.Slots.Length > 0 ? a.Slots[0].ToString() : "-";
            EditorGUI.LabelField(new Rect(row.x + 2, row.y, row.width - 2 - 140, row.height), a.name);
            EditorGUI.LabelField(new Rect(row.x + row.width - 140, row.y, 70, row.height), slotText);
            if (a.NotDone)
            {
                GUI.Label(new Rect(row.x + row.width - 70, row.y, 68, row.height), "Not done", TagNotDone);
            }
            else if (IsManuallyHidden(a))
            {
                GUI.Label(new Rect(row.x + row.width - 70, row.y, 68, row.height), "Hidden", TagHidden);
            }
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
                DrawSelected();
            }
            EditorGUILayout.EndScrollView();
            EditorGUILayout.EndVertical();
        }

        private void DrawSelected()
        {
            using (new EditorGUI.DisabledScope(true))
                EditorGUILayout.ObjectField("Asset", selected, typeof(ApparelObj), false);

            if (selected.NotDone)
            {
                EditorGUILayout.HelpBox("Not done yet: hidden from players on every body and never sold. Mark it done to show it.", MessageType.Warning);
                if (GUILayout.Button("Mark done", GUILayout.Height(24)))
                    MarkAndReload(new[] { selected });
            }
            else
            {
                var message = "Done: visible to players";
                if (IsManuallyHidden(selected))
                    message += " (but manually hidden: Usable In Character Creator is off or Hidden On Bodies is set)";
                EditorGUILayout.HelpBox(message, MessageType.Info);
            }

            EditorGUILayout.BeginHorizontal();
            if (GUILayout.Button("Ping")) EditorGUIUtility.PingObject(selected);
            if (GUILayout.Button("Select in Project")) Selection.activeObject = selected;
            EditorGUILayout.EndHorizontal();

            Editor.CreateCachedEditor(selected, null, ref cachedEditor);
            if (cachedEditor != null) cachedEditor.OnInspectorGUI();
            // The inspector records undo and dirties the asset itself, so nothing extra is done for its edits
        }

        private void MarkAndReload(IEnumerable<ApparelObj> items)
        {
            MarkDone(items, byAssetName);
            needReload = true;
            Repaint();
        }

        /// <summary>
        /// Marks the given apparel done (NotDone off), and every body version of them too (see the class comment).
        /// </summary>
        private static void MarkDone(IEnumerable<ApparelObj> items, Dictionary<string, ApparelObj> byAssetName)
        {
            var targets = new HashSet<ApparelObj>(items);
            foreach (var item in items)
            {
                if (item.Apparel == null) continue;
                foreach (var version in ApparelCatalog.BodyVersionsOf(item.Apparel.Name))
                {
                    if (version.AssetName != null && byAssetName.TryGetValue(version.AssetName, out var loaded) && loaded != null)
                        targets.Add(loaded);
                }
            }

            var marked = new List<string>();
            foreach (var a in targets)
            {
                if (!a.NotDone) continue;
                Undo.RecordObject(a, "Mark apparel done");
                a.NotDone = false;
                EditorUtility.SetDirty(a);
                // Saved one at a time, never SaveAssets(): the editor is shared
                AssetDatabase.SaveAssetIfDirty(a);
                marked.Add(a.name);
            }

            // Saving reimports the assets, which rebuilds the apparel index on its own
            if (marked.Count > 0)
            {
                // Debug.Log is fine here: editor tooling
                Debug.Log($"[ApparelEditorWindow] Marked done: {string.Join(", ", marked)}");
            }
        }

        private static string[] SlotOptions
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

        private static GUIStyle TagNotDone => tagNotDone ?? (tagNotDone = TagStyle(new Color(1f, 0.6f, 0.2f)));
        private static GUIStyle TagHidden => tagHidden ?? (tagHidden = TagStyle(Color.gray));

        private static GUIStyle TagStyle(Color color)
        {
            var style = new GUIStyle(EditorStyles.miniLabel) { alignment = TextAnchor.MiddleRight };
            style.normal.textColor = color;
            return style;
        }
    }
}
#endif
