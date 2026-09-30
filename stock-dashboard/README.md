# Stock Scoring Dashboard

1. `npm install`, copy `.env.example` to `.env` and fill in your Firebase web config.
2. Enable Google sign-in (Auth), Realtime Database and Storage; deploy `database.rules.json` and `storage.rules`.
3. Upload data files to Storage as `data/stocks_YYYY-MM-DD.json` (see `sample-data/`).
4. Storage reads from the browser need CORS on the bucket: `gsutil cors set cors.json gs://<bucket>` with
   `[{"origin":["http://localhost:5173"],"method":["GET"],"maxAgeSeconds":3600}]`.
5. Adapt `src/config/dashboard.config.json` (fields, groups, conditions) to your real data, then `npm run dev`.

## Deploy to Firebase Hosting

1. In the `stock-dashboard` directory, install the Firebase CLI and sign in: `npm install -g firebase-tools`, then `firebase login`.
2. Copy `.env.example` to `.env` and fill in the `VITE_FIREBASE_*` values for the Firebase project you will deploy to. These values are included in the production build.
3. Link this directory to your Firebase project: `firebase use --add`, then select the project. This creates a `.firebaserc` file for the project alias.
4. Build and deploy the dashboard:

   ```sh
   npm run build
   firebase deploy --only hosting
   ```

Firebase Hosting publishes the generated `dist/` directory. The CLI prints the hosted URL when deployment completes. Deploy database and storage rules separately as described above; this Hosting command does not deploy them.

