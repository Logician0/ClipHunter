# Edit a ClipHunter clip

1. Open a project and choose **Edit clip** on a highlight, or open **Clips** and choose **Edit clip** on a finished video.
2. In **Selected clip**, drag the **IN** and **OUT** handles on the single timeline. The source frame and vertical preview jump to each handle as you move it. The times use `mm:ss` or `hh:mm:ss`; you can type either format into the IN and OUT fields. Keep the selection between 20 and 60 seconds.
3. Choose **Play selected clip** to play from IN to OUT. **Play / Pause** lets you inspect the source outside the selected interval.
4. Choose **Gameplay** or **Facecam** to select that crop. Click a box in the source video, drag its interior to move it, or drag its lower-right handle to resize it. To redraw the selected crop, drag in an uncovered part of the frame.
5. Choose **Gameplay only** or **Gameplay + facecam**. For a split, set the facecam height and choose whether it goes on top or bottom. The vertical preview shows moving footage from the current playhead with these crops. It preserves the proportions of each pane.
6. Under **Voice and captions**, choose **Auto detect Hindi / English**, **Hindi**, or **English**, then choose **Recognize speech**. Recognition runs on this Mac using only the selected clip's audio. The editor shows the detected language and editable caption lines when it finishes. Check the words carefully, especially names, slang, and mixed Hindi and English speech.
7. Edit each line's words or its `mm:ss.t` IN and OUT time. Choose **Add line** to write a caption yourself or **Remove** to delete one. Lines cannot overlap or extend beyond the downloaded hour. Click a block in the CC timeline to jump to that line. Keep the hour source video until editing and rendering are complete.
8. Choose a visual caption template and a font card, then adjust the size and colors. The vertical preview shows the caption at the playhead. Choose **No captions** to remove captions entirely from the next preview and render. Switch back to **Captions on** to reuse your saved lines.
9. Choose **Save edits & refresh preview** to save your trim, crop, layout, caption words and style and generate a playable preview. When ready, choose **Render edited clip** to make the final MP4.

The speech model detects the dominant language of the selected audio. If the clip switches languages or the result looks wrong, select the spoken language and run recognition again. This replaces that clip's caption lines, so save a copy of any corrections you want to keep first.

The source video for each hour stays on the Samsung drive until you remove it. In a project, select that hour, expand **Storage**, then choose **Delete downloaded hour video** and confirm. This keeps completed clips and previews but removes the hour-long source and temporary stream cache, so you cannot edit or rerender clips from that hour afterward. The button is disabled while scanning, previews, or renders are active.

Scan progress shows a measured percentage during transcription when the transcript engine reports processed timestamps. Video analysis and clip rendering show an animated activity bar when an accurate percentage is unavailable. Download progress shows received size and speed; YouTube and the connection determine actual transfer speed.
