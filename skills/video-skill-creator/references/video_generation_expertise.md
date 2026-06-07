# Video Generation Expertise

This document outlines essential domain knowledge related to video generation. You must apply these principles when creating new video generation skills.

## Video Generation Foundation Skills

Before creating a new video generation skill, you should review and understand the following vision and audio generation/understanding skills. A new video generation skill will likely use these as sub-skills:

- `add-audio-track`
- `automatic-speech-recognition`
- `change-fps`
- `extract-video-frame`
- `get-image-metadata`
- `get-output-dir`
- `get-video-metadata`
- `image-gen`
- `merge-video`
- `replace-audio`
- `resize-image-resolution`
- `resize-video-resolution`
- `split-audio`
- `split-image`
- `text-to-speech`
- `trim-audio`
- `trim-video`
- `video-gen`
- `video-shot-split`
- `vision-understanding`


Apply the knowledge from these foundation skills to build comprehensive video generation skills. Below are the core concepts to guide you.

## Core Concepts

### Contextual Generation Calls

1. **Stateless by Default**: Each individual CLI call for video, image, or audio generation operates without context. It does not retain memory of previously generated assets.
2. **Passing Context**: You must explicitly pass all necessary contextual information to the CLI call using parameters such as `reference_image`, `reference_video`, `reference_audio`, and `img_path`. Furthermore, you must explicitly describe how to use this context within the `prompt` parameter of the CLI call.

### Input Processing
1. You may receive multiple types of input files, such as text, images, videos, audio files, etc.
2. You should use existing skills to process these input files, such as `vision-understanding`, `automatic-speech-recognition`, etc. to understand the requirements of the video generation task.
3. You can use other skills, such as `split-audio`, `trim-audio`, `video-shot-split`, `trim-video` to process files, and use them as consistent assets.
4. You should reasonably post-process the reference text when necessary to ensure it contains enough information to guide the video generation process.
    - Steps include: expand, organize the reference text, add details, and clarify any ambiguities.

### Long Video Generation

1. **Definition**: Long video generation applies when the target duration exceeds the maximum duration supported by a single API call (e.g., generating a 1-3 minute video when a single call only supports 15 seconds).
2. **Concatenation**: To produce a long video, you must generate and concatenate multiple video segments.
3. **Plot Details**: Long videos require comprehensive plot details. If the user does not provide sufficient narrative context, you must self-generate the necessary plot details to ensure completeness.

### Multi-shot vs. Single-shot Video Generation

1. **Multi-shot Generation**: A single API call can generate a multi-shot video by including the keyword "Shot cut" in the prompt.
   * *Example*: "The scene unfolds slowly amid the city’s neon lights. The camera pans down from high above, weaving through traffic and crowds. Shot cut to a warm yellow street lamp on the corner: the protagonist bends down to tie his shoelaces, wind sweeping fallen leaves past his shoulders."
2. **Single-shot Generation**: A single API call can generate a continuous, single-shot video by including the keyword "Single shot" in the prompt.
   * *Example*: "Single shot: A man is running in the street."

### Consistent Assets

1. **Definition**: Consistent assets ensure uniformity across the video, encompassing visual style, scenes, subjects, characters, vocal timbre, background music, and sound effects.
2. **Formats**: Consistent assets can be texts, images, videos, or audio files; Here are some examples:
    - Image: Three views of a character in one single image, a pure white background can be used as a consistent asset for a character.
    - Audio: The audio generated from the last clip may contain the voice of the character, background music, or sound effects. This audio can be reused as the consistent audio reference for the next clip. When creating a person's reference audio for vocal timbre, generate a short audio clip, with a simple neutral line such as "This is my reference voice." Use it as a `reference_audio` input, not as the final spoken line.
    - Text: the consistent description, including video style, etc.,
3. **Sourcing**: 
    - Assets provided by the user. 
        - The user may provide a character's appearance in the form of an image.
        - The user may provide a character's voice in the form of an audio file or a video clip.
        - Other consistent assets. 
    - If necessary assets are necessary but missing, you must generate them yourself with other skills.(`audio-gen`, `image-gen`, `video-gen`)
    - Intermediate assets: Materials generated during the process (e.g., prior video segments, audio clips, images, and text) can be reused as consistent assets for subsequent generations. 
        - Examples: The audio generated from the last clip can be reused as the consistent audio for the next clip.
4. **Reference-only use**: Consistent assets should be passed as reference inputs to `video-gen` (for example through `reference_image`, `reference_video`, or `reference_audio`) to guide generation, not treated as direct final-output media. For example, a generated audio consistent asset can guide vocal timbre or background-music style, but should not normally replace the generated video's final audio track unless the user explicitly requests audio replacement or the workflow specifically requires a final mixed soundtrack.
5. **Importance**: Utilizing consistent assets is critical for producing coherent and unified videos.

### Synchronized Audio-Visual Generation

When audio and visuals must be synchronized for **visual-audio consistency** or **audio-visual consistency**, such as lip-sync, dance to music, singing, sound-triggered action, or beat-matched editing, pass the reference audio into `video-gen` during video generation. Generating video and audio separately and then using `replace-audio` at the end often produces audio-visual mismatch.

### Consistent Video Generation

1. **Definition**: A consistent video maintains a uniform style, coherent scenes, identical subjects/characters, and a logical plot from start to finish.
   * For example, a character's appearance/voice must remain identical across different shots and generated segments unless the plot dictates a change.
2. **Context-Aware Generation**: As noted in the "Contextual Generation Calls" section, generation is stateless by default. To achieve consistency, you must explicitly pass existing consistent assets as context to the video generation calls (e.g., via `reference_image`, `reference_video`, or `reference_audio` parameters). When recurring elements appear in different segments, explicitly pass the exact same consistent assets in the context and describe how to reference them in the `prompt` to maintain uniformity.
3. **Avoid Bad Practices ❌**: Relying solely on the last frame of a previous clip as the first frame of the next clip is insufficient for maintaining consistency because it provides limited contextual information.
4. **Compulsory Requirement**: Consistent video generation is a mandatory requirement for all video generation skills.

#### Long Multi-shot Video Generation
Long multi-shot videos are created by generating and concatenating a mix of multiple single-shot and multi-shot video segments.

#### Long Single-shot Video Generation
Long single-shot videos are created by concatenating multiple single-shot video segments.
* **Video Continuation**: You must use video continuation techniques to generate long single-shot videos. Video continuation generates the next segment based on the full context of the previous one, ensuring the first frame of the new segment perfectly matches the last frame of the previous one, thereby maintaining the continuous single-shot appearance.


### Planning Before Generation
Before generating any materials, you must plan the generation process, steps includes:
1. Rewrite the main plot when details are missing (including plot details/Narration/Dialogue/Lines for the character(s)).
2. Segment the plot into multiple segments, ensuring that each segment is a logically coherent unit of the plot.
3. Plan the generation process for each segment, which includes:
    - Main plot (the main story or event in this segment. i.e. prompt for video generation.)
    - Duration (in seconds)[Each video segment should not be too short, or too long, longer than the maximum duration supported by the `video-gen` skill.]
    - Number of shots (1, 2, etc.)
    - Scenes (the background environment)
    - Subjects (characters, objects, animals, or plants present)
    - Consistent assets (the specific assets to be referenced for the segment)
4. Save the planning output as a `plan.json` file, detailing the process for every segment.
5. Extract all the consistent assets from the planning output.


## Guidelines for Writing a Video Generation Skill

1. **Explicit Instructions**: Clearly specify which foundation skills should be used at each step of the process.
2. **Detailed Workflows**: Describe the workflow with highly detailed steps, avoiding vague or generalized instructions.
3. **Inject Expertise**: Expose and incorporate all the video-related domain knowledge outlined in this document into the new skill's prompt.

### Common Mistakes to Avoid

When creating video generation skills, **EXPLICITLY INJECT** instructions to prevent the following common pitfalls:

1. **`sessions_spawn` Timeout**: If `sessions_spawn` is utilized, explicitly set its timeout to at least 60 minutes. Shorter timeouts frequently cause long video generation tasks to fail.
2. **Process Polling Timeout**: Ensure the timeout for process polling during individual video segment generation is sufficiently long to prevent premature failures.
3. **Unnecessary Folder Creation**: Do not instruct the skill to manually create folders for storing files (e.g., video segments or images). The system automatically saves them to the correct directories. For other files, such as `plan.json`, you must use the skill `get-output-dir` to get the output directory, and save the file there.
