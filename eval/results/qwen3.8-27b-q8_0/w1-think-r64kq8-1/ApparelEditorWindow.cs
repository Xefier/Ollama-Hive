// FILE: ApparelEditorWindow.cs
#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using System.Linq;
using UnityEditor;
using UnityEngine;

namespace LiminalLabs.CharacterCustomizer
{
    public class ApparelEditorWindow : EditorWindow
    {
        private enum StatusFilter
        {
            All,
            NotDone,
            Done,
            ManuallyHidden
        }

        private List<ApparelObj> allApparel = new List<ApparelObj>();
        private Dictionary<string, ApparelObj> byAssetName = new Dictionary<string, ApparelObj>();
        private ApparelObj selected;
        private string search = "";
        private StatusFilter filter = StatusFilter.All;
        private int slotFilterIndex;
        private Vector2 listScroll;
        private Vector2 detailScroll;
        private bool needsReload;
        private Editor cachedEditor;

        private GUIStyle notDoneTagStyle;
        private GUIStyle hiddenTagStyle;
        private string[] slotOptions;
        private ApparelSlot[] slotValues;

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

            var shown = GetShownApparel();
            DrawToolbar(shown);

            EditorGUILayout.BeginHorizontal();
            DrawList(shown);
            DrawDetails();
            EditorGUILayout.EndHorizontal();

            HandleArrowKeys(shown);
        }

        // Editor tooling: AssetDatabase.FindAssets is acceptable here.
        private void Reload()
        {
            var prevSelected = selected;
            var guids = AssetDatabase.FindAssets("t:ApparelObj");
            allApparel = new List<ApparelObj>();
            byAssetName = new Dictionary<string, ApparelObj>();

            foreach (var guid in guids)
            {
                var path = AssetDatabase.GUIDToAssetPath(guid);
                var asset = AssetDatabase.LoadAssetAtPath<ApparelObj>(path);
                if (asset == null) continue;
                allApparel.Add(asset);
                byAssetName[asset.name] = asset;
            }

            allApparel.Sort((a, b) => string.CompareOrdinal(a.name, b.name));
            selected = allApparel.Find(a => ReferenceEquals(a, prevSelected));
        }

        private void DrawToolbar(List<ApparelObj> shown)
        {
            EditorGUILayout.BeginHorizontal(EditorStyles.toolbar);

            search = EditorGUILayout.TextField(search, EditorStyles.toolbarSearchField, GUILayout.MinWidth(120));

            filter = (StatusFilter)EditorGUILayout.EnumPopup(filter, EditorStyles.toolbarPopup, GUILayout.Width(110));

            slotFilterIndex = EditorGUILayout.Popup(slotFilterIndex, GetSlotOptions(), EditorStyles.toolbarPopup, GUILayout.Width(90));

            GUILayout.FlexibleSpace();
            GUILayout.Label($"{shown.Count} of {allApparel.Count}", EditorStyles.miniLabel);

            var anyNotDoneShown = shown.Any(a => a.NotDone);
            using (new EditorGUI.DisabledScope(!anyNotDoneShown))
            {
                if (GUILayout.Button("Mark all shown done", EditorStyles.toolbarButton))
                {
                    int count = shown.Count(a => a.NotDone);
                    if (EditorUtility.DisplayDialog("Mark apparel done",
                        $"Mark {count} apparel done? They become visible to players.",
                        "Mark done", "Cancel"))
                    {
                        MarkDone(shown.Where(a => a.NotDone), byAssetName);
                        Reload();
                    }
                }
            }

            if (GUILayout.Button("Refresh", EditorStyles.toolbarButton))
            {
                Reload();
            }

            EditorGUILayout.EndHorizontal();
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
                foreach (var apparel in shown)
                {
                    Rect row = EditorGUILayout.GetControlRect(false, 20);

                    if (apparel == selected)
                    {
                        EditorGUI.DrawRect(row, new Color(0.24f, 0.48f, 0.90f, 0.35f));
                    }

                    Rect nameRect = new Rect(row.x, row.y, row.width - 140, row.height);
                    EditorGUI.LabelField(nameRect, apparel.name);

                    Rect slotRect = new Rect(row.x + row.width - 140, row.y, 70, row.height);
                    string slotText = apparel.Slots != null && apparel.Slots.Length > 0
                        ? apparel.Slots[0].ToString()
                        : "-";
                    EditorGUI.LabelField(slotRect, slotText);

                    Rect statusRect = new Rect(row.x + row.width - 70, row.y, 70, row.height);
                    if (apparel.NotDone)
                    {
                        EditorGUI.LabelField(statusRect, "Not done", GetNotDoneTagStyle());
                    }
                    else if (IsManuallyHidden(apparel))
                    {
                        EditorGUI.LabelField(statusRect, "Hidden", GetHiddenTagStyle());
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
                        MarkDone(new[] { selected }, byAssetName);
                        Reload();
                    }
                }
                else
                {
                    string msg = "Done: visible to players";
                    if (IsManuallyHidden(selected))
                    {
                        msg += " (but manually hidden: Usable In Character Creator is off or Hidden On Bodies is set)";
                    }
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
            }

            EditorGUILayout.EndScrollView();
            EditorGUILayout.EndVertical();
        }

        private void HandleArrowKeys(List<ApparelObj> shown)
        {
            if (Event.current.type != EventType.KeyDown || shown.Count == 0) return;

            int idx = shown.IndexOf(selected);
            if (Event.current.keyCode == KeyCode.UpArrow && idx > 0)
            {
                selected = shown[idx - 1];
                Event.current.Use();
            }
            else if (Event.current.keyCode == KeyCode.DownArrow && idx < shown.Count - 1)
            {
                selected = shown[idx + 1];
                Event.current.Use();
            }
        }

        private List<ApparelObj> GetShownApparel()
        {
            var result = new List<ApparelObj>();
            foreach (var a in allApparel)
            {
                if (!MatchesSearch(a)) continue;
                if (!MatchesStatus(a)) continue;
                if (!MatchesSlot(a)) continue;
                result.Add(a);
            }
            return result;
        }

        private bool MatchesSearch(ApparelObj a)
        {
            if (string.IsNullOrEmpty(search)) return true;
            if (!string.IsNullOrEmpty(a.name) && a.name.IndexOf(search, StringComparison.OrdinalIgnoreCase) >= 0)
                return true;
            if (a.Apparel != null)
            {
                if (!string.IsNullOrEmpty(a.Apparel.Name) &&
                    a.Apparel.Name.IndexOf(search, StringComparison.OrdinalIgnoreCase) >= 0)
                    return true;
                if (!string.IsNullOrEmpty(a.Apparel.DisplayName) &&
                    a.Apparel.DisplayName.IndexOf(search, StringComparison.OrdinalIgnoreCase) >= 0)
                    return true;
            }
            return false;
        }

        private bool MatchesStatus(ApparelObj a)
        {
            switch (filter)
            {
                case StatusFilter.All:
                    return true;
                case StatusFilter.NotDone:
                    return a.NotDone;
                case StatusFilter.Done:
                    return !a.NotDone;
                case StatusFilter.ManuallyHidden:
                    return IsManuallyHidden(a);
            }
            return true;
        }

        private bool MatchesSlot(ApparelObj a)
        {
            if (slotFilterIndex <= 0) return true;
            if (a.Slots == null) return false;
            return a.Slots.Contains(GetSlotValues()[slotFilterIndex - 1]);
        }

        private static bool IsManuallyHidden(ApparelObj a)
        {
            return !a.NotDone &&
                   (!a.UsableInCharacterCreator || (a.HiddenOnBodies != null && a.HiddenOnBodies.Length > 0));
        }

        private static void MarkDone(IEnumerable<ApparelObj> items, Dictionary<string, ApparelObj> byAssetName)
        {
            // A garment may have one version per body, linked by name; marking one marks all.
            var all = new HashSet<ApparelObj>();
            foreach (var item in items)
            {
                all.Add(item);
                var versions = ApparelCatalog.BodyVersionsOf(item.Apparel.Name);
                if (versions != null)
                {
                    foreach (var entry in versions)
                    {
                        if (byAssetName.TryGetValue(entry.AssetName, out var version))
                        {
                            all.Add(version);
                        }
                    }
                }
            }

            var marked = new List<string>();
            foreach (var apparel in all)
            {
                if (apparel.NotDone)
                {
                    Undo.RecordObject(apparel, "Mark apparel done");
                    apparel.NotDone = false;
                    EditorUtility.SetDirty(apparel);
                    AssetDatabase.SaveAssetIfDirty(apparel);
                    marked.Add(apparel.name);
                }
            }

            if (marked.Count > 0)
            {
                Debug.Log($"[ApparelEditorWindow] Marked done: {string.Join(", ", marked)}");
            }
        }

        private string[] GetSlotOptions()
        {
            if (slotOptions == null)
            {
                var names = Enum.GetNames(typeof(ApparelSlot));
                slotOptions = new string[names.Length + 1];
                slotOptions[0] = "Any slot";
                Array.Copy(names, 0, slotOptions, 1, names.Length);
            }
            return slotOptions;
        }

        private ApparelSlot[] GetSlotValues()
        {
            if (slotValues == null)
            {
                slotValues = (ApparelSlot[])Enum.GetValues(typeof(ApparelSlot));
            }
            return slotValues;
        }

        private GUIStyle GetNotDoneTagStyle()
        {
            if (notDoneTagStyle == null)
            {
                notDoneTagStyle = new GUIStyle(EditorStyles.miniLabel);
                notDoneTagStyle.normal.textColor = new Color(1f, 0.6f, 0.2f);
            }
            return notDoneTagStyle;
        }

        private GUIStyle GetHiddenTagStyle()
        {
            if (hiddenTagStyle == null)
            {
                hiddenTagStyle = new GUIStyle(EditorStyles.miniLabel);
                hiddenTagStyle.normal.textColor = new Color(0.5f, 0.5f, 0.5f);
            }
            return hiddenTagStyle;
        }
    }
}
#endif
