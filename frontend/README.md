# VoiceLink UI Kit

Build the frontend UI only for a web app called "VoiceLink AI" — an emotion-aware AI voice companion. I already have a working backend (FastAPI) with real APIs, so do NOT generate any backend logic, do NOT use Lovable's built-in AI/database — just build clean, connectable UI screens that I will wire up to my own backend endpoints myself.

Design style: modern, attractive, smooth animations, dark and light theme toggle, feels premium (like a next-gen AI companion app, not a basic chatbot).

Screens needed:

1. **Login / Signup screen**

   - Email + password fields, clean animated transitions between login/signup

   - "Continue" button, error message area

2. **Home / Dashboard**

   - Shows user's name, quick access to: Chat, Voice Call, Voice Library, Personalities, Permissions, Profile

   - Modern card-based layout with icons

3. **Text Chat screen**

   - Chat bubbles (user right, AI left), avatar icons, smooth message animations, typing indicator (animated dots)

   - Message input box with send button

4. **Voice Call screen**

   - Large animated microphone button (pulsing/glowing animation while listening)

   - Status states shown clearly: Listening / Thinking / Speaking (with subtle animations for each state)

   - Live captions area showing transcribed text and AI reply text

   - Waveform or sound animation while AI is speaking

5. **Voice Library screen**

   - Grid/list of voice options (built-in voices): show name, tags (Male/Female/Soft/Deep/Warm/Energetic/Calm), a "preview" play button icon, and a select button

   - Sliders for Speed and Pitch customization

6. **Permission-Based Voice Sharing screen**

   - Section: "My Voice" — record sample button, consent checkbox with text, list of people with access, grant/revoke toggle buttons per person

   - Section: "Request Access" — search/list other users, request button, pending/approved status badges

7. **Personalities screen**

   - Cards for each personality (Friend, Mentor, Teacher, Interview Coach, Study Partner, Travel Guide, Language Tutor) with icon, short description, "Select" button

8. **Conversation History screen**

   - List of past conversations grouped by date, searchable

9. **Profile / Settings screen**

   - User info, theme toggle (dark/light), logout button, account settings

Technical requirements:

- Build as clean React components, one component per screen

- Leave clear placeholder functions for API calls (e.g. `onSendMessage()`, `onLogin()`, `onStartRecording()`, `onGrantAccess()`) that I will connect to my own backend — don't implement any actual logic inside them, just call the placeholder and show loading/success/error states visually

- No hardcoded fake data logic — use props/state so I can plug in real data

- Make sure it's responsive (works well on both desktop and mobile browser)

This is UI-only — I will handle all backend connections, authentication logic, and API integration myself afterward.

This project was built with [Lovable](https://lovable.dev).

## Build with Lovable

Continue developing this project in the [Lovable editor](https://lovable.dev/projects/170b1170-8d22-4d40-bf2d-81e8832009c0).

- **Ship faster**: describe what you want to build and Lovable handles the code.
- **Stay in sync**: every change made in Lovable is committed straight to this repository.
- **Full ownership**: this code is yours. Push to `main` on GitHub and your changes sync back into Lovable, ready for your next prompt.

## Development

Prefer working locally? You need Node.js and npm — [install with nvm](https://github.com/nvm-sh/nvm#installing-and-updating).

```sh
git clone <this-repository-url>
cd <repository-name>
npm i
npm run dev
```
