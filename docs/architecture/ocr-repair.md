# OCR repair design

## Problem

The self-hosted MiniCPM request uses a 4096 token context, one CPU thread, and production card images that can exceed the model's useful input size. These conditions produce HTTP 400 responses and timeouts. Raising the timeout alone does not reduce the input or fix wrong fields. A generic JSON schema prompt failed on three live fixtures.

## Design

Keep the caller contract unchanged: the existing upload API and review flow call `extract_card(images)`. Put provider-specific behavior behind that function. MiniCPM's documented Text Recognition task returns recognized text, which the application parses conservatively into card fields. Vertex AI Gemini and OpenRouter keep the image-to-structured-JSON path. New GCP production environments select Vertex AI with `gemini-3.5-flash-lite`; local Compose keeps its current OpenRouter default. The MiniCPM path remains available to staff through the Ollama provider.

Keep original image storage unchanged. Staff select `vertex`, `ollama`, or `openrouter` in the protected production environment. Vertex uses the VM service identity and the configured Google Cloud project, with no API key. The Google Cloud project is the provider destination for card images. Provider selection is explicit and applies to all card scans. Visitors cannot choose. A provider failure does not send the image to a second provider automatically. The runtime selector preserves unrelated environment bytes and any configured hosted key.

## Alternatives and risks

Increasing only the timeout does not address context size or incorrect fields. The generic JSON schema prompt did not work on the three live fixtures. Automatic external fallback would change where card images are processed without a staff decision.

MiniCPM can be slow on CPU and text recognition can misread card details. The existing review step remains necessary. Vertex AI and OpenRouter send card images to their configured hosted services. Vertex requires the VM service identity to have the `aiplatform.endpoints.predict` permission and the VM to have the `cloud-platform` OAuth scope. OpenRouter still requires a configured key. No provider failure triggers an automatic fallback.

## Upload gateway limits

The API accepts up to two 10 MiB images, but multipart headers add bytes beyond the files themselves. Both Nginx request limits are 22 MiB so the gateway can carry that request. The frontend proxy waits up to 90 seconds for the API, matching the production OCR timeout with a small response margin. Requests without AI processing consent stop at API validation before OCR or image staging.
