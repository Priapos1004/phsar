/** Hand a Blob to the browser's download UI via a throwaway anchor. Callers differ only
 * in where the Blob came from (fetched from the API, or built in the page). */
export function triggerBlobDownload(blob: Blob, filename?: string): void {
	const objectUrl = URL.createObjectURL(blob);
	const anchor = document.createElement('a');
	anchor.href = objectUrl;
	if (filename) anchor.download = filename;
	document.body.appendChild(anchor);
	anchor.click();
	anchor.remove();
	URL.revokeObjectURL(objectUrl);
}
