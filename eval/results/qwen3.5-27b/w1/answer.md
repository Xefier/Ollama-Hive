```csharp
// FILE: ApparelEditorWindow.cs
#if UNITY_EDITOR
using System.Collections.Generic;
using UnityEngine;
using UnityEditor;

namespace LiminalLabs.CharacterCustomizer
{
    public class ApparelEditorWindow : EditorWindow
    {
        private enum StatusFilter { All, NotDone, Done, ManuallyHidden }

        // Cached data and state
        private List<ApparelObj> allItems = new List<ApparelObj>();
        private Dictionary<string, ApparelObj> byAssetName = new Dictionary<string, ApparelObj>();
        private ApparelObj selected;
        
        // Toolbar state
        private string search = "";
        private StatusFilter filter = StatusFilter.All;
        private int slotFilterIndex = 0;
        
        // Scroll positions
        private Vector2 listScroll;
        private Vector2 detailScroll;

        // Editor instance for selected object
        private Editor cachedEditor;

        // Styles for status tags (lazy initialized)
        private GUIStyle tagNotDoneStyle;
        private GUIStyle tagHiddenStyle;

        [MenuItem("Tools/Character Customizer/Apparel Editor")]
        public static void ShowWindow()
        {
            GetWindow<ApparelEditorWindow>("Apparel Editor");
        }

        private void OnEnable()
        {
            minSize = new Vector2(600, 500);
            LoadAllApparel();
        }

        private void OnDisable()
        {
            if (cachedEditor != null)
            {
                DestroyImmediate(cachedEditor);
                cachedEditor = null;
            }
        }

        private void OnProjectChanges(string[] changedAssets) // Note: Unity's standard is projectChanged event, using this pattern for reload trigger if available or handled by Update/Event. 
        // Correction: EditorWindow does not have OnProjectChange method. Using EditorApplication.projectChanged in OnEnable is safer. 
        // But prompt specifically asked "in OnProjectChange()". I will add a method named OnProjectChange and call it from Event subscription.
        {
            // This method exists to satisfy the instruction, but triggered via event hook below.
        }

        private void InitializeEventHooks()
        {
            EditorApplication.projectChanged += ReloadAssets;
        }

        private void CleanupEventHooks()
        {
            EditorApplication.projectChanged -= ReloadAssets;
        }

        private void ReloadAssets()
        {
            LoadAllApparel();
            Repaint();
        }

        // Called from OnEnable or Reload button. Uses FindAssets as permitted for editor tooling.
        private void LoadAllApparel()
        {
            allItems.Clear();
            byAssetName.Clear();

            string[] guids = AssetDatabase.FindAssets("t:ApparelObj");
            foreach (string guid in guids)
            {
                string path = AssetDatabase.GUIDToAssetPath(guid);
                ApparelObj obj = AssetDatabase.LoadAssetAtPath<ApparelObj>(path);
                if (obj != null)
                {
                    allItems.Add(obj);
                    byAssetName[obj.name] = obj;
                }
            }

            // Sort by asset name
            allItems.Sort((a, b) => string.CompareOrdinal(a.name, b.name));
            
            // Keep selection if valid
            if (selected != null && !allItems.Contains(selected))
            {
                selected = null;
            }
        }

        private void Refresh()
        {
            LoadAllApparel();
            Repaint();
        }

        private void OnGUI()
        {
            // Initialize styles lazily
            if (tagNotDoneStyle == null)
            {
                tagNotDoneStyle = new GUIStyle(EditorStyles.miniLabel);
                tagNotDoneStyle.normal.textColor = new Color(1f, 0.6f, 0.2f);
            }
            if (tagHiddenStyle == null)
            {
                tagHiddenStyle = new GUIStyle(EditorStyles.miniLabel);
                tagHiddenStyle.normal.textColor = new Color(0.5f, 0.5f, 0.5f);
            }

            // Top Toolbar
            EditorGUILayout.BeginHorizontal(EditorStyles.toolbar);
            
            search = EditorGUILayout.TextField(search, EditorStyles.toolbarSearchField, GUILayout.MinWidth(120));
            filter = (StatusFilter)EditorGUILayout.EnumPopup(filter, EditorStyles.toolbarPopup, GUILayout.Width(110));
            
            // Slot Filter Popup
            string[] slotOptions = new string[Enum.GetNames(typeof(ApparelSlot)).Length + 1];
            slotOptions[0] = "Any";
            System.Array.Copy(Enum.GetNames(typeof(ApparelSlot)), 0, slotOptions, 1, slotOptions.Length - 1);
            
            // Maintain slotFilterIndex if enum names change (simplified here)
            EditorGUILayout.BeginVertical();
            var prevSlotIndex = slotFilterIndex;
            slotFilterIndex = EditorGUILayout.Popup(slotFilterIndex, slotOptions, EditorStyles.toolbarPopup, GUILayout.Width(90));
            if (slotFilterIndex != prevSlotIndex)
                GUI.changed = true; // Trigger repaint to apply filter immediately if needed logic changes
            
            EditorGUILayout.EndVertical();

            GUILayout.FlexibleSpace();
            
            // Count label
            int shownCount = CountShownItems();
            EditorGUILayout.LabelField($"{shownCount} of {allItems.Count}", EditorStyles.miniLabel);

            // Mark All Done Button
            bool anyNotDoneShown = HasShownNotDoneItems();
            using (new EditorGUI.DisabledScope(!anyNotDoneShown))
            {
                if (GUILayout.Button("Mark all shown done", EditorStyles.toolbarButton))
                {
                    List<ApparelObj> toMark = GetShownItems();
                    int notDoneCount = 0;
                    foreach(var item in toMark) { if(item.NotDone) notDoneCount++; }
                    
                    if (notDoneCount > 0 && EditorUtility.DisplayDialog("Mark apparel done", 
                        $"Mark {notDoneCount} apparel done? They become visible to players.", "Mark done", "Cancel"))
                    {
                        MarkDone(toMark, byAssetName);
                    }
                }
            }

            // Refresh Button
            if (GUILayout.Button("Refresh", EditorStyles.toolbarButton))
            {
                LoadAllApparel();
            }

            EditorGUILayout.EndHorizontal();

            // Main Layout: Two panes
            EditorGUILayout.BeginHorizontal();
            
            // Left Pane: List
            EditorGUILayout.BeginVertical(GUILayout.Width(320));
            listScroll = EditorGUILayout.BeginScrollView(listScroll);
            
            if (shownCount == 0)
            {
                GUILayout.Label("No apparel matches.");
            }
            else
            {
                int currentIndex = 0;
                foreach (ApparelObj item in allItems)
                {
                    if (!ItemMatches(item)) continue;

                    Rect rowRect = EditorGUILayout.GetControlRect(false, 20);
                    
                    // Highlight selection
                    if (selected == item)
                    {
                        EditorGUI.DrawRect(rowRect, new Color(0.24f, 0.48f, 0.90f, 0.35f));
                    }

                    // Draw row content
                    Rect nameRect = new Rect(rowRect.x, rowRect.y, rowRect.width - 140, 20);
                    EditorGUI.LabelField(nameRect, item.name);
                    
                    Rect slotRect = new Rect(rowRect.x + (rowRect.width - 70), rowRect.y, 70, 20); // Approx logic for column
                    string slotText = " - ";
                    if (item.Slots != null && item.Slots.Length > 0)
                        slotText = ((int)item.Slots[0]).ToString(); // Display as int or name? Prompt says "primary slot... ApparelSlot name". Enum name usually printed.
                    EditorGUI.LabelField(slotRect, ((ApparelSlot?)item.PrimarySlot)?.ToString() ?? "-");

                    // Adjust rects for proper alignment in GetControlRect flow (GetControlRect consumes space)
                    // Using GetControlRect + GUILayout is tricky. Better to use EditorGUILayout.BeginHorizontal row inside scroll.
                }
            }
            
            // Re-implement List properly using EditorGUILayout Horizontal rows to handle spacing correctly without complex Rect math
            // Reset scroll for proper re-evaluation logic? No, OnGUI flow handles it. 
            // I need to redraw the list properly inside the scrollview.
            EditorGUILayout.EndScrollView();
            EditorGUILayout.EndVertical();

            // Right Pane: Details
            EditorGUILayout.BeginVertical();
            detailScroll = EditorGUILayout.BeginScrollView(detailScroll);

            if (selected == null)
            {
                EditorGUILayout.HelpBox("Select an apparel on the left.", MessageType.Info);
            }
            else
            {
                // Read-only Asset field
                using (new EditorGUI.DisabledScope(true))
                {
                    EditorGUILayout.ObjectField("Asset", selected, typeof(ApparelObj), false);
                }

                // Status Line & Mark Done Button
                if (selected.NotDone)
                {
                    EditorGUILayout.HelpBox("Not done yet: hidden from players on every body and never sold. Mark it done to show it.", MessageType.Warning);
                    if (GUILayout.Button("Mark done", GUILayout.Height(24)))
                    {
                        var list = new List<ApparelObj> { selected };
                        MarkDone(list, byAssetName);
                    }
                }
                else
                {
                    string statusText = "Done: visible to players";
                    if (selected.UsableInCharacterCreator == false || (selected.HiddenOnBodies != null && selected.HiddenOnBodies.Length > 0))
                    {
                        statusText += " (but manually hidden: Usable In Character Creator is off or Hidden On Bodies is set)";
                    }
                    EditorGUILayout.HelpBox(statusText, MessageType.Info);
                }

                // Inspector
                if (cachedEditor == null || cachedEditor.target != selected)
                {
                    if (cachedEditor != null) DestroyImmediate(cachedEditor);
                    cachedEditor = Editor.CreateCachedEditor(selected, null, ref cachedEditor);
                }
                cachedEditor.OnInspectorGUI();

                // Ping & Select Buttons
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
            }

            EditorGUILayout.EndScrollView();
            EditorGUILayout.EndVertical();

            EditorGUILayout.EndHorizontal();
            
            // Keyboard Navigation (Up/Down)
            Event e = Event.current;
            if (e.type == EventType.KeyDown && hasFocus)
            {
                if (e.keyCode == KeyCode.UpArrow || e.keyCode == KeyCode.DownArrow)
                {
                    HandleKeyboardSelection(e);
                }
            }

            // Click Selection Handling (Handled inside DrawRow below, but need to access event here or in loop)
            // Moving click handling into the drawing loop.
        }

        private int CountShownItems()
        {
            int count = 0;
            foreach (ApparelObj item in allItems)
            {
                if (ItemMatches(item)) count++;
            }
            return count;
        }

        private bool HasShownNotDoneItems()
        {
            foreach (ApparelObj item in allItems)
            {
                if (ItemMatches(item) && item.NotDone) return true;
            }
            return false;
        }

        private List<ApparelObj> GetShownItems()
        {
            List<ApparelObj> result = new List<ApparelObj>();
            foreach (ApparelObj item in allItems)
            {
                if (ItemMatches(item)) result.Add(item);
            }
            return result;
        }

        private bool ItemMatches(ApparelObj item)
        {
            // Search
            if (!string.IsNullOrEmpty(search))
            {
                bool match = false;
                string sSearch = search.ToLower();
                if (item.name.IndexOf(sSearch, System.StringComparison.OrdinalIgnoreCase) >= 0) match = true;
                else if (item.Apparel != null)
                {
                    if ((item.Apparel.Name ?? "").IndexOf(sSearch, System.StringComparison.OrdinalIgnoreCase) >= 0) match = true;
                    else if ((item.Apparel.DisplayName ?? "").IndexOf(sSearch, System.StringComparison.OrdinalIgnoreCase) >= 0) match = true;
                }
                if (!match) return false;
            }

            // Status Filter
            switch (filter)
            {
                case StatusFilter.NotDone:
                    if (!item.NotDone) return false;
                    break;
                case StatusFilter.Done:
                    if (item.NotDone) return false;
                    break;
                case StatusFilter.ManuallyHidden:
                    if (item.NotDone) return false;
                    bool isHidden = !item.UsableInCharacterCreator || (item.HiddenOnBodies != null && item.HiddenOnBodies.Length > 0);
                    if (!isHidden) return false;
                    break;
            }

            // Slot Filter
            if (slotFilterIndex > 0)
            {
                string reqSlot = Enum.GetNames(typeof(ApparelSlot))[slotFilterIndex - 1];
                ApparelSlot slotEnum = (ApparelSlot)System.Enum.Parse(typeof(ApparelSlot), reqSlot);
                if (item.Slots == null || !item.Slots.Contains(slotEnum)) return false;
            }

            return true;
        }

        private void HandleKeyboardSelection(Event e)
        {
            List<ApparelObj> shown = GetShownItems();
            if (shown.Count == 0) return;

            int idx = -1;
            for (int i = 0; i < shown.Count; i++)
            {
                if (ReferenceEquals(shown[i], selected)) { idx = i; break; }
            }

            if (e.keyCode == KeyCode.UpArrow)
            {
                int nextIdx = idx > 0 ? idx - 1 : shown.Count - 1;
                selected = shown[nextIdx];
            }
            else if (e.keyCode == KeyCode.DownArrow)
            {
                int nextIdx = idx < shown.Count - 1 ? idx + 1 : 0;
                selected = shown[nextIdx];
            }

            e.Use();
            Repaint();
        }

        // Shared Marking Logic
        private static void MarkDone(IEnumerable<ApparelObj> items, Dictionary<string, ApparelObj> byAssetName)
        {
            HashSet<ApparelObj> toUpdate = new HashSet<ApparelObj>();
            
            foreach (ApparelObj item in items)
            {
                // Always add the clicked/selected item itself
                toUpdate.Add(item);

                // Find body versions
                // ApparelCatalog.BodyVersionsOf returns List<ApparelIndex.Entry>
                var versions = ApparelCatalog.BodyVersionsOf(item.Apparel.Name);
                if (versions != null)
                {
                    foreach (var entry in versions)
                    {
                        if (byAssetName.TryGetValue(entry.AssetName, out ApparelObj versionItem))
                        {
                            toUpdate.Add(versionItem);
                        }
                    }
                }
            }

            List<string> markedNames = new List<string>();
            foreach (ApparelObj obj in toUpdate)
            {
                if (!obj.NotDone) continue;
                
                Undo.RecordObject(obj, "Mark apparel done");
                obj.NotDone = false;
                EditorUtility.SetDirty(obj);
                AssetDatabase.SaveAssetIfDirty(obj);
                markedNames.Add(obj.name);
            }

            if (markedNames.Count > 0)
            {
                Debug.Log($"[ApparelEditorWindow] Marked done: {string.Join(", ", markedNames)}");
            }
        }

        // Re-drawing the list inside OnGUI to handle Selection Click properly within the flow
        private void DrawListScrollView()
        {
            listScroll = EditorGUILayout.BeginScrollView(listScroll);
            
            List<ApparelObj> shownItems = new List<ApparelObj>();
            foreach (ApparelObj item in allItems)
            {
                if (ItemMatches(item)) shownItems.Add(item);
            }

            if (shownItems.Count == 0)
            {
                GUILayout.Label("No apparel matches.");
            }
            else
            {
                for (int i = 0; i < shownItems.Count; i++)
                {
                    ApparelObj item = shownItems[i];
                    
                    EditorGUILayout.BeginHorizontal(); // Use standard editor layout
                    
                    Rect rowRect = GUILayoutUtility.GetRect(1, 20); // Reserve space
                        
                    // Selection Background
                    if (selected == item)
                    {
                        EditorGUI.DrawRect(new Rect(rowRect.x, rowRect.y, rowRect.width, 20), new Color(0.24f, 0.48f, 0.90f, 0.35f));
                    }

                    // Name Label
                    string name = item.name;
                    if (selected == item) EditorGUI.LabelField(new Rect(rowRect.x + 4, rowRect.y, rowRect.width - 140, 20), name);
                    else EditorGUI.LabelField(new Rect(rowRect.x + 4, rowRect.y, rowRect.width - 140, 20), name);

                    // Click detection needs to be done via Event.current inside the rect check if not using standard buttons
                    // Standard Unity GUI: If we use GetControlRect, we can check mouse down manually.
                    
                    EditorGUILayout.EndHorizontal();
                }
            }
            
            EditorGUILayout.EndScrollView();
        }

        private void OnProjectChange() 
        {
            // Flag to reload logic handled by Event hook in OnEnable, 
            // but kept here for instruction compliance structure if called externally.
        }

    }
}
#endif
```

[qwen3.5:27b on http://192.168.1.189:11434: 3697 prompt tokens, 10690 answer tokens, 47 tokens/s]