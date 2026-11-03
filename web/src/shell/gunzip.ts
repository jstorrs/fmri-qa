/** Gunzip without a Blob: WebKit cannot read a Blob inside a worker on file:// (NotReadableError). */
export const gunzip = async (bytes: Uint8Array<ArrayBuffer>): Promise<Uint8Array<ArrayBuffer>> => {
  const source = new ReadableStream<Uint8Array<ArrayBuffer>>({
    start(controller) {
      controller.enqueue(bytes);
      controller.close();
    },
  });
  return new Uint8Array(await new Response(source.pipeThrough(new DecompressionStream('gzip'))).arrayBuffer());
};
