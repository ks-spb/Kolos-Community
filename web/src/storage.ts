import type { Experiment } from './engine.js';
/** One IDB transaction per snapshot. A failed save is always surfaced to the user. */
export class ExperimentStore {
  private database: Promise<IDBDatabase> | null = null;
  private open(): Promise<IDBDatabase> {
    if (!this.database) this.database = new Promise((resolve, reject) => {
      if (!globalThis.indexedDB) { reject(new Error('IndexedDB недоступна')); return; }
      const request = indexedDB.open('kolos-graph-lab-v1', 1);
      request.onupgradeneeded = () => request.result.createObjectStore('experiments');
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
      request.onblocked = () => reject(new Error('Хранилище заблокировано другой вкладкой'));
    });
    return this.database;
  }
  async load(): Promise<unknown> {
    const db = await this.open();
    return new Promise((resolve, reject) => {
      const request = db.transaction('experiments').objectStore('experiments').get('current');
      request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
    });
  }
  async save(experiment: Experiment): Promise<void> {
    const db = await this.open();
    return new Promise((resolve, reject) => {
      const tx = db.transaction('experiments', 'readwrite');
      tx.objectStore('experiments').put(experiment, 'current');
      tx.oncomplete = () => resolve(); tx.onerror = () => reject(tx.error); tx.onabort = () => reject(tx.error);
    });
  }
}
