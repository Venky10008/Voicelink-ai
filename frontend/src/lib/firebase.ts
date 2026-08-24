/**
 * SSR-safe Firebase wrapper.
 *
 * Firebase is loaded with dynamic `import()`s only inside the functions below,
 * so it never runs during server-side rendering (TanStack Start) — it only
 * executes in browser event handlers.
 *
 * Config comes from `VITE_FIREBASE_*` env vars (see `.env.example`).
 */

export type FirebaseAuthResult = {
  idToken: string;
  name?: string;
  email?: string;
};

function firebaseConfig() {
  return {
    apiKey: import.meta.env.VITE_FIREBASE_API_KEY as string | undefined,
    authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN as string | undefined,
    projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID as string | undefined,
    storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET as string | undefined,
    messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID as string | undefined,
    appId: import.meta.env.VITE_FIREBASE_APP_ID as string | undefined,
  };
}

export function isFirebaseConfigured(): boolean {
  const cfg = firebaseConfig();
  return Boolean(cfg.apiKey && cfg.authDomain && cfg.projectId && cfg.appId);
}

export function firebaseConfigError(): string {
  return (
    "Firebase is not configured. Add VITE_FIREBASE_API_KEY, " +
    "VITE_FIREBASE_AUTH_DOMAIN, VITE_FIREBASE_PROJECT_ID and VITE_FIREBASE_APP_ID " +
    "to frontend/.env (see frontend/.env.example)."
  );
}

type FirebaseUser = {
  uid: string;
  displayName: string | null;
  email: string | null;
};

async function getFirebaseAuth() {
  const [{ initializeApp, getApps }, { getAuth }] = await Promise.all([
    import("firebase/app"),
    import("firebase/auth"),
  ]);
  const app = getApps().length ? getApps()[0] : initializeApp(firebaseConfig());
  return getAuth(app);
}

async function toAuthResult(fbUser: FirebaseUser): Promise<FirebaseAuthResult> {
  const { getIdToken } = await import("firebase/auth");
  const token = await getIdToken(fbUser as never);
  return {
    idToken: token,
    name: fbUser.displayName ?? undefined,
    email: fbUser.email ?? undefined,
  };
}

export async function signInWithEmail(
  email: string,
  password: string,
): Promise<FirebaseAuthResult> {
  const auth = await getFirebaseAuth();
  const { signInWithEmailAndPassword } = await import("firebase/auth");
  const credential = await signInWithEmailAndPassword(auth, email, password);
  return toAuthResult(credential.user as unknown as FirebaseUser);
}

export async function signUpWithEmail(
  email: string,
  password: string,
): Promise<FirebaseAuthResult> {
  const auth = await getFirebaseAuth();
  const { createUserWithEmailAndPassword } = await import("firebase/auth");
  const credential = await createUserWithEmailAndPassword(auth, email, password);
  return toAuthResult(credential.user as unknown as FirebaseUser);
}

export async function signOutFirebase(): Promise<void> {
  const auth = await getFirebaseAuth();
  const { signOut } = await import("firebase/auth");
  await signOut(auth);
}

type AuthUserLike = { name?: string; email?: string };

/**
 * Subscribe to Firebase ID-token changes.
 *
 * Firebase ID tokens expire every ~hour; the SDK rotates them in the
 * background and `onIdTokenChanged` fires each time. It also restores the
 * persisted session on page load and fires immediately with a FRESH token,
 * which is what keeps the app working after a day away instead of sending
 * the backend a long-dead token from localStorage.
 *
 * Returns an unsubscribe function. SSR-safe (Firebase loads lazily).
 */
export async function subscribeIdToken(
  onToken: (token: string | null, user?: AuthUserLike) => void,
): Promise<() => void> {
  if (!isFirebaseConfigured()) return () => {};
  const auth = await getFirebaseAuth();
  const { onIdTokenChanged, getIdToken } = await import("firebase/auth");
  return onIdTokenChanged(auth, (fbUser) => {
    if (!fbUser) {
      onToken(null);
      return;
    }
    getIdToken(fbUser as never)
      .then((token) =>
        onToken(token, {
          name: fbUser.displayName ?? undefined,
          email: fbUser.email ?? undefined,
        }),
      )
      .catch(() => onToken(null));
  });
}

export async function sendPasswordResetEmail(email: string): Promise<void> {
  const auth = await getFirebaseAuth();
  const { sendPasswordResetEmail } = await import("firebase/auth");
  await sendPasswordResetEmail(auth, email);
}

/** Friendlier message for the password-reset flow (no password is being entered). */
export function resetPasswordErrorMessage(error: unknown): string {
  const code = (error as { code?: string } | null)?.code ?? "";
  if (code === "auth/user-not-found") return "No account found with that email.";
  if (code === "auth/invalid-email") return "Please enter a valid email address.";
  return firebaseErrorMessage(error);
}

/** Map common Firebase auth error codes to friendly messages. */
export function firebaseErrorMessage(error: unknown): string {
  const code = (error as { code?: string } | null)?.code ?? "";
  switch (code) {
    case "auth/invalid-credential":
    case "auth/wrong-password":
    case "auth/user-not-found":
      return "Incorrect email or password.";
    case "auth/email-already-in-use":
      return "An account with this email already exists.";
    case "auth/weak-password":
      return "Password should be at least 6 characters.";
    case "auth/invalid-email":
      return "Please enter a valid email address.";
    case "auth/too-many-requests":
      return "Too many attempts. Try again later.";
    case "auth/network-request-failed":
      return "Network error — check your connection.";
    default:
      return error instanceof Error ? error.message : "Authentication failed.";
  }
}
